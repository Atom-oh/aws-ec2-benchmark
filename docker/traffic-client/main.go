// traffic-client is an open-loop HTTP arrival generator. All counters are interval
// deltas, except inflight (a gauge). Request ownership never changes across phases.
package main

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"math"
	"math/bits"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"sync"
	"syscall"
	"time"
)

const maxDispatchLag = 10 * time.Millisecond

type Config struct {
	Target         string   `json:"target"`
	Instance       string   `json:"instance"`
	RunID          string   `json:"run_id"`
	StartEpoch     float64  `json:"start_epoch"`
	TimeoutSeconds int      `json:"timeout_seconds"`
	MaxInflight    int      `json:"max_inflight"`
	Phases         []Phase  `json:"phases"`
	Cleanup        *Cleanup `json:"cleanup"`
	AllowIdle      bool     `json:"allow_idle,omitempty"`
}

type Phase struct {
	Name            string  `json:"name"`
	DurationSeconds int     `json:"duration_seconds"`
	RateRPS         float64 `json:"rate_rps"`
	RampSeconds     int     `json:"ramp_seconds"`
	FromRateRPS     float64 `json:"from_rate_rps"`
}

type Cleanup struct {
	ServerJob     string `json:"server_job"`
	ServerService string `json:"server_service"`
	Namespace     string `json:"namespace"`
}

var resourceName = regexp.MustCompile(`^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$`)

func (c Cleanup) validate() error {
	if c.Namespace != "benchmark" {
		return errors.New("cleanup namespace must be benchmark")
	}
	for _, name := range []string{c.ServerJob, c.ServerService} {
		if len(name) > 253 || !resourceName.MatchString(name) {
			return errors.New("cleanup requires exact Kubernetes resource names")
		}
		for _, label := range strings.Split(name, ".") {
			if len(label) == 0 || len(label) > 63 || strings.HasPrefix(label, "-") || strings.HasSuffix(label, "-") {
				return errors.New("invalid cleanup resource name")
			}
		}
	}
	return nil
}

func finitePositive(v float64) bool { return v > 0 && !math.IsInf(v, 0) && !math.IsNaN(v) }

func (c Config) Validate() error {
	u, err := url.Parse(c.Target)
	if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Hostname() == "" || u.User != nil || u.Fragment != "" {
		return errors.New("target must be an absolute http(s) URL without credentials or fragment")
	}
	if u.Port() != "" {
		if _, err := net.LookupPort("tcp", u.Port()); err != nil {
			return fmt.Errorf("invalid target port: %w", err)
		}
	}
	if strings.TrimSpace(c.Instance) == "" || strings.TrimSpace(c.RunID) == "" {
		return errors.New("instance and run_id required")
	}
	if !finitePositive(c.StartEpoch) || c.StartEpoch > float64(math.MaxInt64)/1e9 {
		return errors.New("start_epoch must be a positive finite representable epoch")
	}
	if c.TimeoutSeconds != 2 {
		return errors.New("timeout_seconds must be 2")
	}
	if c.MaxInflight < 1 || c.MaxInflight > 2048 {
		return errors.New("max_inflight must be in [1,2048]")
	}
	if len(c.Phases) == 0 {
		return errors.New("at least one phase required")
	}
	seen := make(map[string]bool)
	total := 0.0
	for _, p := range c.Phases {
		if strings.TrimSpace(p.Name) == "" || seen[p.Name] {
			return errors.New("phases must have unique nonempty names")
		}
		seen[p.Name] = true
		if p.DurationSeconds <= 0 || (!finitePositive(p.RateRPS) && !(c.AllowIdle && p.RateRPS == 0)) || p.RampSeconds < 0 || p.RampSeconds > p.DurationSeconds {
			return fmt.Errorf("invalid phase %q duration, rate or ramp", p.Name)
		}
		if math.IsNaN(p.FromRateRPS) || math.IsInf(p.FromRateRPS, 0) || p.FromRateRPS < 0 || (p.RampSeconds > 0 && p.FromRateRPS == 0 && !c.AllowIdle) {
			return fmt.Errorf("invalid phase %q from_rate_rps", p.Name)
		}
		total += float64(p.DurationSeconds)
		// Integer counters and nanosecond offsets must remain exactly representable.
		integral := p.RateRPS*float64(p.DurationSeconds-p.RampSeconds) + float64(p.RampSeconds)*(p.FromRateRPS/2+p.RateRPS/2)
		if (!finitePositive(integral) && !(c.AllowIdle && integral == 0)) || integral > 1<<53 || total >= float64(math.MaxInt64)/1e9 || c.StartEpoch+total > float64(math.MaxInt64)/1e9 {
			return errors.New("schedule exceeds representable limits")
		}
	}
	if c.Cleanup != nil {
		return c.Cleanup.validate()
	}
	return nil
}

func readConfig(r io.Reader) (Config, error) {
	var c Config
	d := json.NewDecoder(r)
	d.DisallowUnknownFields()
	if err := d.Decode(&c); err != nil {
		return c, err
	}
	var extra any
	if err := d.Decode(&extra); err != io.EOF {
		return c, errors.New("config must contain exactly one JSON object")
	}
	return c, c.Validate()
}

func epoch(t time.Time) float64 { return float64(t.Unix()) + float64(t.Nanosecond())/1e9 }

type phasePlan struct {
	phase  Phase
	offset time.Duration
	count  uint64
}

func (p phasePlan) integral(t float64) float64 {
	d := float64(p.phase.DurationSeconds)
	t = math.Max(0, math.Min(t, d))
	r := float64(p.phase.RampSeconds)
	if r == 0 {
		return t * p.phase.RateRPS
	}
	x := math.Min(t, r)
	return x*p.phase.FromRateRPS + (p.phase.RateRPS-p.phase.FromRateRPS)*x*x/(2*r) + math.Max(0, t-r)*p.phase.RateRPS
}

// Arrival k occurs when the integrated rate reaches k, starting at k=0.
// Hence [phase start, phase end) offers ceil(integrated rate) arrivals; no
// accumulated timer drift and no burst catch-up proportional to an old backlog.
func (p phasePlan) arrival(k uint64) time.Duration {
	// The initial arrival is exactly the phase boundary, including a ramp from
	// zero. Idle phases have count=0 and never dispatch this scheduling boundary.
	if k == 0 {
		return p.offset
	}
	y := float64(k)
	r := float64(p.phase.RampSeconds)
	t := 0.0
	if r == 0 {
		t = y / p.phase.RateRPS
	} else {
		rampCount := r * (p.phase.FromRateRPS/2 + p.phase.RateRPS/2)
		if y >= rampCount {
			t = r
			if p.phase.RateRPS > 0 {
				t += (y - rampCount) / p.phase.RateRPS
			}
		} else {
			slope := (p.phase.RateRPS - p.phase.FromRateRPS) / r
			// Rationalized quadratic root is stable for either ramp direction.
			t = 2 * y / (p.phase.FromRateRPS + math.Sqrt(p.phase.FromRateRPS*p.phase.FromRateRPS+2*slope*y))
		}
	}
	return p.offset + time.Duration(t*float64(time.Second))
}

func (p phasePlan) due(elapsed time.Duration) uint64 {
	if p.count == 0 || elapsed < p.offset {
		return 0
	}
	t := (elapsed - p.offset).Seconds()
	if t >= float64(p.phase.DurationSeconds) {
		return p.count
	}
	n := uint64(math.Floor(p.integral(t))) + 1
	return min(n, p.count)
}

func compileSchedule(c Config) ([]phasePlan, time.Duration) {
	var out []phasePlan
	var offset time.Duration
	for _, p := range c.Phases {
		plan := phasePlan{phase: p, offset: offset}
		plan.count = uint64(math.Ceil(plan.integral(float64(p.DurationSeconds))))
		out = append(out, plan)
		offset += time.Duration(p.DurationSeconds) * time.Second
	}
	return out, offset
}

func histogramIndex(u uint64) int {
	if u == 0 {
		u = 1
	}
	if u < 64 {
		return int(u)
	}
	shift := bits.Len64(u) - 7
	return 64 + shift*64 + int(u>>shift) - 64
}

func histogramUpper(index int) uint64 {
	if index < 64 {
		return uint64(index)
	}
	shift := (index - 64) / 64
	mantissa := (index-64)%64 + 64
	return (uint64(mantissa+1) << shift) - 1
}

type Sample struct {
	Timestamp        float64        `json:"timestamp"`
	ElapsedSec       float64        `json:"elapsed_sec"`
	IntervalStartSec float64        `json:"interval_start_sec"`
	IntervalEndSec   float64        `json:"interval_end_sec"`
	Phase            string         `json:"phase"`
	Offered          uint64         `json:"offered"`
	Started          uint64         `json:"started"`
	Completed        uint64         `json:"completed"`
	Success          uint64         `json:"success"`
	HTTPErrors       uint64         `json:"http_errors"`
	TransportErrors  uint64         `json:"transport_errors"`
	Timeouts         uint64         `json:"timeouts"`
	Dropped          uint64         `json:"dropped"`
	LatencyCount     uint64         `json:"latency_count"`
	LatencySumUS     uint64         `json:"latency_sum_us"`
	Histogram        map[int]uint64 `json:"histogram"`
	ClientCPUPct     float64        `json:"client_cpu_pct"`
	MaxDispatchLagMS float64        `json:"max_dispatch_lag_ms"`
	Inflight         int            `json:"inflight"`
}

type Status struct {
	Outcome             string          `json:"outcome"`
	Instance            string          `json:"instance"`
	RunID               string          `json:"run_id"`
	ScheduledStart      float64         `json:"scheduled_start"`
	ScheduledEnd        float64         `json:"scheduled_end"`
	ActualStart         float64         `json:"actual_start"`
	ActualEnd           float64         `json:"actual_end"`
	Error               string          `json:"error,omitempty"`
	Totals              Sample          `json:"totals"`
	Cleanup             []CleanupResult `json:"cleanup"`
	Warnings            []string        `json:"warnings"`
	HistogramDefinition string          `json:"histogram_definition"`
	MaxDispatchLagMS    float64         `json:"dispatch_lateness_limit_ms"`
	NumCPU              int             `json:"num_cpu"`
	DropReasons         DropReasons     `json:"drop_reasons"`
	StartLatenessMS     float64         `json:"start_lateness_ms"`
}

type DropReasons struct {
	Capacity  uint64 `json:"capacity"`
	Lateness  uint64 `json:"lateness"`
	Cancelled uint64 `json:"cancelled"`
}

func validateFinalCounts(s Sample, expected uint64) error {
	if s.Offered != expected || s.Started+s.Dropped != s.Offered || s.Completed != s.Started ||
		s.Success+s.HTTPErrors+s.TransportErrors+s.Timeouts != s.Completed || s.LatencyCount != s.Completed || s.Inflight != 0 {
		return fmt.Errorf("incomplete request accounting: planned=%d offered=%d started=%d dropped=%d completed=%d latency_count=%d inflight=%d", expected, s.Offered, s.Started, s.Dropped, s.Completed, s.LatencyCount, s.Inflight)
	}
	return nil
}

type counters struct {
	mu    sync.Mutex
	rows  []Sample
	total Sample
	drops DropReasons
}

func newCounters(n int) *counters { return &counters{rows: make([]Sample, n)} }

func (s *counters) offer(phase int, n uint64, reason string, lag time.Duration) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.offerLocked(phase, n, reason, lag)
}

// offerLocked makes offered and its started/drop classification indivisible to
// the sampler. Pending worker reservations are not classified until dispatch.
func (s *counters) offerLocked(phase int, n uint64, reason string, lag time.Duration) {
	r := &s.rows[phase]
	r.Offered += n
	s.total.Offered += n
	if reason != "" {
		r.Dropped += n
		s.total.Dropped += n
		switch reason {
		case "capacity":
			s.drops.Capacity += n
		case "lateness":
			s.drops.Lateness += n
		case "cancelled":
			s.drops.Cancelled += n
		}
	} else {
		r.Started += n
		s.total.Started += n
		r.Inflight += int(n)
		s.total.Inflight += int(n)
	}
	r.MaxDispatchLagMS = math.Max(r.MaxDispatchLagMS, float64(lag)/float64(time.Millisecond))
}

func (s *counters) complete(phase int, kind string, latency, lag time.Duration) {
	s.mu.Lock()
	defer s.mu.Unlock()
	r := &s.rows[phase]
	us := uint64(max(latency.Microseconds(), 1))
	for _, c := range []*Sample{r, &s.total} {
		c.Completed++
		c.Inflight--
		c.LatencyCount++
		c.LatencySumUS += us
		switch kind {
		case "success":
			c.Success++
		case "http":
			c.HTTPErrors++
		case "timeout":
			c.Timeouts++
		default:
			c.TransportErrors++
		}
	}
	if r.Histogram == nil {
		r.Histogram = make(map[int]uint64)
	}
	r.Histogram[histogramIndex(us)]++
	r.MaxDispatchLagMS = math.Max(r.MaxDispatchLagMS, float64(lag)/float64(time.Millisecond))
}

func cpuSeconds() (float64, error) {
	var r syscall.Rusage
	if err := syscall.Getrusage(syscall.RUSAGE_SELF, &r); err != nil {
		return 0, err
	}
	return float64(r.Utime.Sec+r.Stime.Sec) + float64(r.Utime.Usec+r.Stime.Usec)/1e6, nil
}

type sampler struct {
	stats       *counters
	plans       []phasePlan
	start       time.Time
	enc         *json.Encoder
	lastCPU     float64
	lastElapsed float64
	now         func() time.Time
}

func (s *sampler) flush() error {
	// Capture one boundary while counter writers are excluded. A caller's cached
	// time could otherwise precede events that win the lock before this snapshot.
	s.stats.mu.Lock()
	cpu, err := cpuSeconds()
	if err != nil {
		s.stats.mu.Unlock()
		return fmt.Errorf("client rusage: %w", err)
	}
	clock := s.now
	if clock == nil {
		clock = time.Now
	}
	now := clock()
	pct := 0.0
	// Every counter and CPU row uses the same scheduled-epoch interval. A failed
	// cancellation before the epoch has a [0,0] bookkeeping interval.
	elapsed := max(now.Sub(s.start), 0)
	end := math.Max(elapsed.Seconds(), s.lastElapsed)
	begin := s.lastElapsed
	if delta := end - begin; delta > 0 {
		pct = math.Max(0, math.Min(100, (cpu-s.lastCPU)/delta/float64(runtime.NumCPU())*100))
	}
	s.lastCPU = cpu
	s.lastElapsed = end
	rows := make([]Sample, 0, len(s.plans))
	for i, p := range s.plans {
		r := s.stats.rows[i]
		active := elapsed >= p.offset && elapsed < p.offset+time.Duration(p.phase.DurationSeconds)*time.Second
		if r.Offered != 0 || r.Completed != 0 || (end > begin && (active || r.Inflight != 0)) {
			r.Timestamp = epoch(now)
			r.ElapsedSec = end
			r.IntervalStartSec = begin
			r.IntervalEndSec = end
			r.Phase = p.phase.Name
			r.ClientCPUPct = pct
			if r.Histogram == nil {
				r.Histogram = map[int]uint64{}
			}
			rows = append(rows, r)
		}
		s.stats.rows[i] = Sample{Inflight: r.Inflight}
	}
	s.stats.mu.Unlock()
	for _, r := range rows {
		if err := s.enc.Encode(r); err != nil {
			return fmt.Errorf("write samples: %w", err)
		}
	}
	return nil
}

func newHTTPClient(limit int) *http.Client {
	tr := http.DefaultTransport.(*http.Transport).Clone()
	tr.Proxy = nil
	tr.MaxConnsPerHost = limit
	tr.MaxIdleConns = limit
	tr.MaxIdleConnsPerHost = limit
	tr.DialContext = (&net.Dialer{Timeout: 2 * time.Second, KeepAlive: 30 * time.Second}).DialContext
	tr.TLSHandshakeTimeout = 2 * time.Second
	tr.ResponseHeaderTimeout = 2 * time.Second
	return &http.Client{Transport: tr, Timeout: 2 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
}

func performRequest(ctx context.Context, client *http.Client, target string, planned time.Time, phase int, stats *counters) {
	reqCtx, cancel := context.WithDeadline(ctx, planned.Add(2*time.Second))
	defer cancel()
	req, err := http.NewRequestWithContext(reqCtx, http.MethodGet, target, nil)
	// Check fresh monotonic time after acquiring the accounting lock: a worker
	// can be paused after its scheduler reservation, or wait through a flush.
	// There is never a started-counter rollback into a subsequent sample.
	stats.mu.Lock()
	dispatched := time.Now()
	lag := max(dispatched.Sub(planned), 0)
	reason := ""
	if ctx.Err() != nil {
		reason = "cancelled"
	} else if lag > maxDispatchLag {
		reason = "lateness"
	}
	stats.offerLocked(phase, 1, reason, lag)
	stats.mu.Unlock()
	if reason != "" {
		return
	}
	kind := "transport"
	if err == nil {
		resp, doErr := client.Do(req)
		err = doErr
		if resp != nil {
			_, bodyErr := io.Copy(io.Discard, resp.Body)
			closeErr := resp.Body.Close()
			if err == nil {
				err = errors.Join(bodyErr, closeErr)
			}
			if err == nil {
				if resp.StatusCode >= 200 && resp.StatusCode < 300 {
					kind = "success"
				} else {
					kind = "http"
				}
			}
		}
	}
	if err != nil {
		var ne net.Error
		if errors.Is(err, context.DeadlineExceeded) || (errors.As(err, &ne) && ne.Timeout()) {
			kind = "timeout"
		}
	}
	stats.complete(phase, kind, time.Since(planned), lag)
}

type MetricSample struct {
	Timestamp float64         `json:"timestamp"`
	Metric    string          `json:"metric"`
	Data      json.RawMessage `json:"data,omitempty"`
	Error     string          `json:"error,omitempty"`
}

var metrics = []struct{ name, path, tag string }{
	{"system.cpu.usage", "system.cpu.usage", ""}, {"process.cpu.usage", "process.cpu.usage", ""}, {"process.uptime", "process.uptime", ""},
	{"jvm.gc.pause", "jvm.gc.pause", ""}, {"jvm.gc.memory.allocated", "jvm.gc.memory.allocated", ""}, {"jvm.gc.memory.promoted", "jvm.gc.memory.promoted", ""}, {"jvm.gc.live.data.size", "jvm.gc.live.data.size", ""}, {"jvm.gc.max.data.size", "jvm.gc.max.data.size", ""},
	{"jvm.memory.used.heap", "jvm.memory.used", "area:heap"}, {"jvm.memory.committed.heap", "jvm.memory.committed", "area:heap"}, {"jvm.memory.max.heap", "jvm.memory.max", "area:heap"}, {"jvm.memory.used.nonheap", "jvm.memory.used", "area:nonheap"},
}

// All metrics in a poll share its epoch timestamp. HTTP/optional-metric failures
// produce error rows; only a persistence failure is fatal to the poll/run.
func pollMetrics(ctx context.Context, c Config, enc *json.Encoder, client *http.Client) error {
	stamp := epoch(time.Now())
	// One budget for the complete poll preserves the 10s cadence even when the
	// server stalls. Every skipped/expired optional metric still gets an error row.
	ctx, cancelPoll := context.WithTimeout(ctx, 2*time.Second)
	defer cancelPoll()
	base, _ := url.Parse(c.Target)
	for _, m := range metrics {
		u := *base
		u.Path = "/actuator/metrics/" + m.path
		u.RawPath = ""
		u.RawQuery = ""
		if m.tag != "" {
			q := url.Values{}
			q.Set("tag", m.tag)
			u.RawQuery = q.Encode()
		}
		row := MetricSample{Timestamp: stamp, Metric: m.name}
		reqCtx, cancel := context.WithTimeout(ctx, 2*time.Second)
		req, err := http.NewRequestWithContext(reqCtx, http.MethodGet, u.String(), nil)
		if err == nil {
			resp, doErr := client.Do(req)
			err = doErr
			if resp != nil {
				data, readErr := io.ReadAll(io.LimitReader(resp.Body, 1024*1024+1))
				resp.Body.Close()
				if err == nil {
					err = readErr
				}
				if err == nil && resp.StatusCode != http.StatusOK {
					err = fmt.Errorf("HTTP %d", resp.StatusCode)
				}
				if err == nil && (len(data) > 1024*1024 || !json.Valid(data) || len(data) == 0 || data[0] != '{') {
					err = errors.New("invalid or oversized metric JSON")
				}
				if err == nil {
					row.Data = json.RawMessage(data)
				}
			}
		}
		cancel()
		if err != nil {
			row.Error = err.Error()
		}
		if err := enc.Encode(row); err != nil {
			return fmt.Errorf("write metrics: %w", err)
		}
	}
	return nil
}

type CleanupResult struct {
	Resource   string `json:"resource"`
	Name       string `json:"name"`
	Success    bool   `json:"success"`
	Attempts   int    `json:"attempts"`
	HTTPStatus int    `json:"http_status,omitempty"`
	Error      string `json:"error,omitempty"`
}

func cleanupOwnResources(ctx context.Context, c Cleanup, api, token string, client *http.Client) []CleanupResult {
	if err := c.validate(); err != nil {
		return []CleanupResult{{Error: err.Error()}}
	}
	out := make([]CleanupResult, 0, 2)
	for _, r := range []struct{ kind, name, path string }{{"Job", c.ServerJob, "/apis/batch/v1/namespaces/benchmark/jobs/"}, {"Service", c.ServerService, "/api/v1/namespaces/benchmark/services/"}} {
		row := CleanupResult{Resource: r.kind, Name: r.name}
		for attempt := 1; attempt <= 3; attempt++ {
			row.Attempts = attempt
			reqCtx, cancel := context.WithTimeout(ctx, 2*time.Second)
			req, err := http.NewRequestWithContext(reqCtx, http.MethodDelete, strings.TrimRight(api, "/")+r.path+url.PathEscape(r.name), strings.NewReader(`{"propagationPolicy":"Background"}`))
			if err == nil {
				req.Header.Set("Authorization", "Bearer "+strings.TrimSpace(token))
				req.Header.Set("Content-Type", "application/json")
				resp, doErr := client.Do(req)
				err = doErr
				if resp != nil {
					row.HTTPStatus = resp.StatusCode
					io.Copy(io.Discard, io.LimitReader(resp.Body, 65536))
					resp.Body.Close()
					if err == nil {
						if (resp.StatusCode >= 200 && resp.StatusCode < 300) || resp.StatusCode == 404 {
							row.Success = true
						} else {
							err = fmt.Errorf("HTTP %d", resp.StatusCode)
						}
					}
				}
			}
			cancel()
			if row.Success {
				row.Error = ""
				break
			}
			if err != nil {
				row.Error = err.Error()
			}
			if ctx.Err() != nil || (row.HTTPStatus >= 400 && row.HTTPStatus < 500 && row.HTTPStatus != 429) || attempt == 3 {
				break
			}
			timer := time.NewTimer(time.Duration(attempt) * 100 * time.Millisecond)
			select {
			case <-ctx.Done():
				timer.Stop()
			case <-timer.C:
			}
		}
		out = append(out, row)
	}
	return out
}

func mountedCleanup(c Cleanup) []CleanupResult {
	const dir = "/var/run/secrets/kubernetes.io/serviceaccount"
	failed := func(err error) []CleanupResult {
		return []CleanupResult{{Resource: "Job", Name: c.ServerJob, Error: err.Error()}, {Resource: "Service", Name: c.ServerService, Error: err.Error()}}
	}
	token, err := os.ReadFile(filepath.Join(dir, "token"))
	if err != nil {
		return failed(err)
	}
	ca, err := os.ReadFile(filepath.Join(dir, "ca.crt"))
	if err != nil {
		return failed(err)
	}
	roots := x509.NewCertPool()
	if !roots.AppendCertsFromPEM(ca) {
		return failed(errors.New("invalid Kubernetes CA"))
	}
	host := os.Getenv("KUBERNETES_SERVICE_HOST")
	port := os.Getenv("KUBERNETES_SERVICE_PORT_HTTPS")
	if port == "" {
		port = "443"
	}
	if host == "" || len(strings.TrimSpace(string(token))) == 0 {
		return failed(errors.New("missing Kubernetes host or service-account token"))
	}
	client := newHTTPClient(1)
	defer client.CloseIdleConnections()
	client.Transport.(*http.Transport).TLSClientConfig = &tls.Config{RootCAs: roots, MinVersion: tls.VersionTLS12}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	return cleanupOwnResources(ctx, c, "https://"+net.JoinHostPort(host, port), string(token), client)
}

func writeJSON(path string, value any) error {
	b, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err = os.WriteFile(tmp, append(b, '\n'), 0644); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// Run reserves only MaxInflight traffic requests; metrics use a separate single
// connection. The deployment must reserve client CPU and memory independently.
func Run(ctx context.Context, c Config, dir string) (status Status, runErr error) {
	if err := c.Validate(); err != nil {
		return status, err
	}
	plans, horizon := compileSchedule(c)
	start := time.Unix(0, int64(c.StartEpoch*1e9))
	status = Status{Outcome: "RUNNING", Instance: c.Instance, RunID: c.RunID, ScheduledStart: c.StartEpoch, ScheduledEnd: c.StartEpoch + horizon.Seconds(), Warnings: []string{}, Cleanup: []CleanupResult{}, NumCPU: runtime.NumCPU(), MaxDispatchLagMS: maxDispatchLag.Seconds() * 1000,
		HistogramDefinition: "positive microseconds clamped to 1; u<64: index=u; otherwise shift=bits.Len64(u)-7, index=64+shift*64+(u>>shift)-64; upper(index>=64)=(((index-64)%64+65)<<((index-64)/64))-1; upper error <1/64 (1.563%); latency includes planned dispatch delay and every completed outcome; drops have no latency; offered phase counts=ceil(integrated rate)"}
	stats := newCounters(len(plans))
	var expectedOffered uint64
	for _, p := range plans {
		expectedOffered += p.count
	}
	if err := os.MkdirAll(dir, 0755); err != nil {
		return status, err
	}
	for _, name := range []string{"config.json", "status.json", "samples.ndjson", "metrics.ndjson"} {
		if _, err := os.Lstat(filepath.Join(dir, name)); !os.IsNotExist(err) {
			status.Outcome = "FAILED"
			status.Error = "results directory already contains output or cannot be inspected"
			return status, errors.New(status.Error)
		}
	}
	defer func() {
		status.ActualEnd = epoch(time.Now())
		stats.mu.Lock()
		status.Totals = stats.total
		status.DropReasons = stats.drops
		stats.mu.Unlock()
		runErr = errors.Join(runErr, validateFinalCounts(status.Totals, expectedOffered))
		if status.DropReasons.Capacity > 0 {
			status.Warnings = append(status.Warnings, "local capacity drops: max_inflight saturated; target response backlog can cause this")
		}
		if status.DropReasons.Lateness > 0 {
			status.Warnings = append(status.Warnings, "local lateness drops: dispatch exceeded 10ms; generator validity requires analysis")
		}
		if status.Totals.Success == 0 {
			runErr = errors.Join(runErr, errors.New("zero successful requests"))
		}
		if c.Cleanup != nil {
			status.Cleanup = mountedCleanup(*c.Cleanup)
			for _, r := range status.Cleanup {
				if !r.Success {
					runErr = errors.Join(runErr, fmt.Errorf("cleanup %s %s: %s", r.Resource, r.Name, r.Error))
				}
			}
		}
		if ctx.Err() != nil && !errors.Is(runErr, ctx.Err()) {
			runErr = errors.Join(runErr, fmt.Errorf("interrupted: %w", ctx.Err()))
		}
		status.Outcome = "COMPLETE"
		if runErr != nil {
			status.Outcome = "FAILED"
			status.Error = runErr.Error()
		}
		if err := writeJSON(filepath.Join(dir, "status.json"), status); err != nil {
			runErr = errors.Join(runErr, err)
			status.Outcome = "FAILED"
			status.Error = runErr.Error()
		}
	}()
	if err := writeJSON(filepath.Join(dir, "config.json"), c); err != nil {
		return status, err
	}
	if err := writeJSON(filepath.Join(dir, "status.json"), status); err != nil {
		return status, err
	}
	samples, err := os.OpenFile(filepath.Join(dir, "samples.ndjson"), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0644)
	if err != nil {
		return status, err
	}
	defer func() { runErr = errors.Join(runErr, samples.Close()) }()
	metricFile, err := os.OpenFile(filepath.Join(dir, "metrics.ndjson"), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0644)
	if err != nil {
		return status, err
	}
	defer func() { runErr = errors.Join(runErr, metricFile.Close()) }()
	// Convert the external wall epoch once to a monotonic anchor. Wall-clock steps
	// during the run must not move planned arrivals or phase boundaries.
	now := time.Now()
	start = now.Add(start.Sub(now))
	runCtx, cancel := context.WithCancel(ctx)
	defer cancel()
	client := newHTTPClient(c.MaxInflight)
	defer client.CloseIdleConnections()
	metricClient := newHTTPClient(1)
	defer metricClient.CloseIdleConnections()
	if delay := time.Until(start); delay > 0 {
		timer := time.NewTimer(delay)
		select {
		case <-timer.C:
		case <-ctx.Done():
			timer.Stop()
		}
	}
	status.ActualStart = epoch(time.Now())
	status.StartLatenessMS = math.Max(0, (status.ActualStart-c.StartEpoch)*1000)
	if status.StartLatenessMS > maxDispatchLag.Seconds()*1000 {
		status.Warnings = append(status.Warnings, fmt.Sprintf("late start: %.3fms after scheduled epoch; intended offered arrivals are preserved", status.StartLatenessMS))
	}
	if err := writeJSON(filepath.Join(dir, "status.json"), status); err != nil {
		return status, err
	}
	cpu, err := cpuSeconds()
	if err != nil {
		return status, err
	}
	samp := sampler{stats: stats, plans: plans, start: start, enc: json.NewEncoder(samples), lastCPU: cpu, lastElapsed: 0}
	metricCtx, stopMetrics := context.WithCancel(runCtx)
	metricDone := make(chan error, 1)
	go func() {
		enc := json.NewEncoder(metricFile)
		ticker := time.NewTicker(10 * time.Second)
		defer ticker.Stop()
		for {
			if err := pollMetrics(metricCtx, c, enc, metricClient); err != nil {
				metricDone <- err
				return
			}
			select {
			case <-metricCtx.Done():
				metricDone <- nil
				return
			case <-ticker.C:
			}
		}
	}()
	defer func() { stopMetrics(); runErr = errors.Join(runErr, <-metricDone) }()
	var workers sync.WaitGroup
	slots := make(chan struct{}, c.MaxInflight)
	next := make([]uint64, len(plans))
	cursor := 0
	sampleAt := start.Add(time.Second)
	for {
		now = time.Now()
		elapsed := now.Sub(start)
		interrupted := ctx.Err() != nil || runErr != nil
		for i := cursor; i < len(plans); i++ {
			p := plans[i]
			if !interrupted && p.offset > elapsed {
				break
			}
			due := p.due(elapsed)
			if interrupted {
				due = p.count
			}
			if due <= next[i] {
				if next[i] == p.count {
					cursor = i + 1
				}
				continue
			}
			lag := now.Sub(start.Add(p.arrival(next[i])))
			stale := p.due(elapsed - maxDispatchLag - time.Nanosecond)
			if interrupted {
				stale = due
			}
			stale = min(stale, due)
			if stale > next[i] {
				reason := "lateness"
				if interrupted {
					reason = "cancelled"
				}
				stats.offer(i, stale-next[i], reason, max(lag, 0))
				next[i] = stale
			}
			for next[i] < due {
				planned := start.Add(p.arrival(next[i]))
				lag = now.Sub(planned)
				select {
				case slots <- struct{}{}:
					workers.Add(1)
					go func(phase int, at time.Time) {
						defer workers.Done()
						defer func() { <-slots }()
						performRequest(runCtx, client, c.Target, at, phase, stats)
					}(i, planned)
					next[i]++
				default:
					stats.offer(i, due-next[i], "capacity", max(lag, 0))
					next[i] = due
				}
			}
			if next[i] == p.count {
				cursor = i + 1
			}
		}
		if !now.Before(sampleAt) {
			runErr = errors.Join(runErr, samp.flush())
			sampleAt = start.Add((elapsed/time.Second + 1) * time.Second)
		}
		if interrupted || elapsed >= horizon {
			break
		}
		wake := minTime(sampleAt, start.Add(horizon))
		if cursor < len(plans) {
			wake = minTime(wake, start.Add(plans[cursor].arrival(next[cursor])))
		}
		// Coalesce high-rate arrivals into <=1ms scheduling batches, reducing timer
		// overhead without changing each arrival's latency origin or offered count.
		if wake.Before(now.Add(time.Millisecond)) {
			wake = minTime(now.Add(time.Millisecond), minTime(sampleAt, start.Add(horizon)))
		}
		timer := time.NewTimer(max(time.Until(wake), 0))
		select {
		case <-ctx.Done():
			timer.Stop()
		case <-timer.C:
		}
	}
	if ctx.Err() != nil {
		runErr = errors.Join(runErr, fmt.Errorf("interrupted: %w", ctx.Err()))
	}
	if runErr != nil {
		cancel()
	}
	drained := make(chan struct{})
	go func() { workers.Wait(); close(drained) }()
	deadline := time.NewTimer(2250 * time.Millisecond)
	defer deadline.Stop()
	cancelCh := ctx.Done()
	for waiting := true; waiting; {
		timer := time.NewTimer(max(time.Until(sampleAt), 0))
		select {
		case <-drained:
			waiting = false
		case <-cancelCh:
			cancel()
			runErr = errors.Join(runErr, fmt.Errorf("interrupted during drain: %w", ctx.Err()))
			cancelCh = nil
		case <-deadline.C:
			cancel()
			runErr = errors.Join(runErr, errors.New("bounded drain expired"))
			waiting = false
		case <-timer.C:
			runErr = errors.Join(runErr, samp.flush())
			sampleAt = sampleAt.Add(time.Second)
		}
		timer.Stop()
	}
	stopMetrics()
	runErr = errors.Join(runErr, samp.flush())
	return status, runErr
}

func minTime(a, b time.Time) time.Time {
	if a.Before(b) {
		return a
	}
	return b
}

func main() {
	configPath := flag.String("config", "", "JSON config path")
	results := flag.String("results", "", "results directory")
	flag.Parse()
	if *configPath == "" || *results == "" || flag.NArg() != 0 {
		fmt.Fprintln(os.Stderr, "usage: traffic-client -config PATH -results DIR")
		os.Exit(2)
	}
	f, err := os.Open(*configPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	c, err := readConfig(f)
	f.Close()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	status, err := Run(ctx, c, *results)
	fmt.Fprintf(os.Stderr, "%s offered=%d success=%d dropped=%d\n", status.Outcome, status.Totals.Offered, status.Totals.Success, status.Totals.Dropped)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
