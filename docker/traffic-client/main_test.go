package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func testConfig(target string) Config {
	return Config{Target: target, Instance: "m7i.xlarge", RunID: "test", StartEpoch: epoch(time.Now().Add(50 * time.Millisecond)), TimeoutSeconds: 2, MaxInflight: 8, Phases: []Phase{{Name: "low", DurationSeconds: 1, RateRPS: 20}}}
}

func TestConfigValidation(t *testing.T) {
	good := testConfig("http://localhost:8080/")
	if err := good.Validate(); err != nil {
		t.Fatal(err)
	}
	cases := map[string]func(*Config){
		"scheme":          func(c *Config) { c.Target = "file:///tmp/foo" },
		"host":            func(c *Config) { c.Target = "http:///" },
		"credentials":     func(c *Config) { c.Target = "http://user:password@localhost/" },
		"timeout":         func(c *Config) { c.TimeoutSeconds = 0 },
		"connections":     func(c *Config) { c.MaxInflight = 0 },
		"excess capacity": func(c *Config) { c.MaxInflight = 2049 },
		"empty":           func(c *Config) { c.Phases = nil },
		"duplicate":       func(c *Config) { c.Phases = append(c.Phases, c.Phases[0]) },
		"unnamed":         func(c *Config) { c.Phases[0].Name = "" },
		"duration":        func(c *Config) { c.Phases[0].DurationSeconds = 0 },
		"rate":            func(c *Config) { c.Phases[0].RateRPS = 0 },
		"nan":             func(c *Config) { c.Phases[0].RateRPS = math.NaN() },
		"infinity":        func(c *Config) { c.Phases[0].RateRPS = math.Inf(1) },
		"ramp too long":   func(c *Config) { c.Phases[0].RampSeconds = 2; c.Phases[0].FromRateRPS = 10 },
		"ramp from zero":  func(c *Config) { c.Phases[0].RampSeconds = 1 },
		"negative ramp":   func(c *Config) { c.Phases[0].RampSeconds = -1 },
		"epoch":           func(c *Config) { c.StartEpoch = math.Inf(1) },
		"instance":        func(c *Config) { c.Instance = "" },
		"run":             func(c *Config) { c.RunID = "" },
		"cleanup namespace": func(c *Config) {
			c.Cleanup = &Cleanup{Namespace: "default", ServerJob: "own-job", ServerService: "own-svc"}
		},
		"cleanup wildcard": func(c *Config) {
			c.Cleanup = &Cleanup{Namespace: "benchmark", ServerJob: "*", ServerService: "own-svc"}
		},
		"cleanup escape": func(c *Config) {
			c.Cleanup = &Cleanup{Namespace: "benchmark", ServerJob: "../other", ServerService: "own-svc"}
		},
	}
	for name, change := range cases {
		t.Run(name, func(t *testing.T) {
			c := good
			c.Phases = append([]Phase(nil), good.Phases...)
			change(&c)
			if c.Validate() == nil {
				t.Fatal("invalid config accepted")
			}
		})
	}
	if _, err := readConfig(strings.NewReader(`{"target":"http://localhost","unknown":1}`)); err == nil {
		t.Fatal("unknown config field accepted")
	}
}

func TestHistogramPositiveUpperBounds(t *testing.T) {
	for _, tc := range []struct {
		us    uint64
		index int
		upper uint64
	}{{0, 1, 1}, {1, 1, 1}, {63, 63, 63}, {64, 64, 64}, {127, 127, 127}, {128, 128, 129}, {255, 191, 255}, {256, 192, 259}, {1000, 317, 1007}, {2000000, 1018, 2015231}} {
		i := histogramIndex(tc.us)
		if i != tc.index || histogramUpper(i) != tc.upper {
			t.Fatalf("%d: index=%d upper=%d want %d/%d", tc.us, i, histogramUpper(i), tc.index, tc.upper)
		}
	}
	for u := uint64(64); u < 10000000; u = u*11/10 + 1 {
		upper := histogramUpper(histogramIndex(u))
		if upper < u || float64(upper-u)/float64(u) >= 1.0/64 {
			t.Fatalf("unbounded bin %d -> %d", u, upper)
		}
	}
}

func TestLinearRampAndExactTransitions(t *testing.T) {
	c := testConfig("http://localhost/")
	c.Phases = []Phase{{Name: "rise", DurationSeconds: 2, RateRPS: 6, FromRateRPS: 2, RampSeconds: 2}, {Name: "fall", DurationSeconds: 2, RateRPS: 2, FromRateRPS: 6, RampSeconds: 1}}
	plans, horizon := compileSchedule(c)
	if horizon != 4*time.Second || plans[0].count != 8 || plans[1].count != 6 {
		t.Fatalf("schedule=%+v horizon=%v", plans, horizon)
	}
	// Rise integral is 2t+t²: its third arrival (ordinal 2) is sqrt(3)-1.
	if math.Abs(plans[0].arrival(2).Seconds()-(math.Sqrt(3)-1)) > 1e-8 {
		t.Fatal("ramp inversion wrong")
	}
	if math.Abs(plans[1].arrival(4).Seconds()-3) > 1e-8 {
		t.Fatal("ramp tail transition wrong")
	}
	if plans[0].due(2*time.Second) != 8 || plans[1].due(2*time.Second-time.Nanosecond) != 0 || plans[1].due(2*time.Second) != 1 || plans[1].due(4*time.Second) != 6 {
		t.Fatal("phase boundary accounting wrong")
	}
	for _, p := range plans {
		for i := uint64(0); i < p.count; i++ {
			at := p.arrival(i)
			if p.due(at+time.Nanosecond) != i+1 {
				t.Fatalf("arrival %d of %s inconsistent", i, p.phase.Name)
			}
		}
	}
}

func idleConfig(t *testing.T, c Config) Config {
	t.Helper()
	b, err := json.Marshal(c)
	if err != nil {
		t.Fatal(err)
	}
	var fields map[string]any
	if err := json.Unmarshal(b, &fields); err != nil {
		t.Fatal(err)
	}
	fields["allow_idle"] = true
	b, err = json.Marshal(fields)
	if err != nil {
		t.Fatal(err)
	}
	out, err := readConfig(bytes.NewReader(b))
	if err != nil {
		t.Fatalf("allow_idle config rejected: %v", err)
	}
	return out
}

func TestAllowIdleOptInValidation(t *testing.T) {
	c := testConfig("http://localhost/")
	c.Phases = []Phase{{Name: "idle", DurationSeconds: 1}, {Name: "rise", DurationSeconds: 1, RateRPS: 4, RampSeconds: 1}, {Name: "fall", DurationSeconds: 2, FromRateRPS: 4, RampSeconds: 1}}
	if c.Validate() == nil {
		t.Fatal("zero rate accepted without allow_idle")
	}
	idle := idleConfig(t, c)
	for _, bad := range []float64{-1, math.NaN(), math.Inf(1), math.Inf(-1)} {
		for _, field := range []string{"rate", "from"} {
			broken := idle
			broken.Phases = append([]Phase(nil), idle.Phases...)
			if field == "rate" {
				broken.Phases[1].RateRPS = bad
			} else {
				broken.Phases[1].FromRateRPS = bad
			}
			if broken.Validate() == nil {
				t.Fatalf("allow_idle accepted invalid %s %v", field, bad)
			}
		}
	}
	// The legacy positive target still requires a positive ramp source.
	strict := testConfig("http://localhost/")
	strict.Phases[0].RampSeconds = 1
	if strict.Validate() == nil {
		t.Fatal("zero ramp source accepted without allow_idle")
	}
	idleConfig(t, strict)
	b, err := json.Marshal(idle)
	if err != nil {
		t.Fatal(err)
	}
	var fields map[string]any
	if err := json.Unmarshal(b, &fields); err != nil {
		t.Fatal(err)
	}
	fields["allow_idle"] = false
	b, err = json.Marshal(fields)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := readConfig(bytes.NewReader(b)); err == nil {
		t.Fatal("explicit allow_idle=false accepted idle schedule")
	}
}

func TestIdleAndZeroEndpointRampArrivalConservation(t *testing.T) {
	c := testConfig("http://localhost/")
	c.Phases = []Phase{{Name: "idle", DurationSeconds: 1}, {Name: "rise", DurationSeconds: 1, RateRPS: 4, RampSeconds: 1}, {Name: "fall", DurationSeconds: 2, FromRateRPS: 4, RampSeconds: 1}, {Name: "tail-idle", DurationSeconds: 1}}
	plans, horizon := compileSchedule(c)
	if horizon != 5*time.Second {
		t.Fatalf("idle phases changed horizon %v", horizon)
	}
	for i, want := range []uint64{0, 2, 2, 0} {
		p := plans[i]
		if p.count != want || p.arrival(0) != p.offset {
			t.Fatalf("unsafe initial arrival/count for %s: count=%d arrival=%v offset=%v", p.phase.Name, p.count, p.arrival(0), p.offset)
		}
		if p.due(p.offset+time.Duration(p.phase.DurationSeconds)*time.Second) != want {
			t.Fatalf("lost phase count %s", p.phase.Name)
		}
		if want == 0 && (p.due(p.offset) != 0 || p.due(p.offset+500*time.Millisecond) != 0) {
			t.Fatalf("phantom idle arrival %s", p.phase.Name)
		}
		for k := uint64(0); k < p.count; k++ {
			at := p.arrival(k)
			if at < p.offset || at >= p.offset+time.Duration(p.phase.DurationSeconds)*time.Second || p.due(at+time.Nanosecond) != k+1 {
				t.Fatalf("invalid arrival %d in %s at %v", k, p.phase.Name, at)
			}
		}
	}
	if math.Abs(plans[1].arrival(1).Seconds()-(1+math.Sqrt(.5))) > 1e-8 {
		t.Fatal("zero-to-positive ramp inverse wrong")
	}
	if math.Abs(plans[2].arrival(1).Seconds()-(3-math.Sqrt(.5))) > 1e-8 {
		t.Fatal("positive-to-zero ramp inverse wrong")
	}
	if plans[2].due(3*time.Second) != 2 || plans[2].due(3500*time.Millisecond) != 2 {
		t.Fatal("zero ramp tail added phantom arrivals")
	}
	boost := Phase{Name: "boost", DurationSeconds: 60, RateRPS: 13708.50977650215, FromRateRPS: 0, RampSeconds: 60}
	c.Phases = []Phase{boost, {Name: "fall", DurationSeconds: 120, RateRPS: 0, FromRateRPS: 13708.50977650215, RampSeconds: 60}}
	plans, _ = compileSchedule(c)
	for _, p := range plans {
		if p.count != 411256 {
			t.Fatalf("fractional boost ramp lost counts: %s=%d", p.phase.Name, p.count)
		}
	}
}

func TestAllowIdleHTTPConservationAndFinalDrain(t *testing.T) {
	for _, tc := range []struct {
		name   string
		phases []Phase
		delay  time.Duration
		want   uint64
	}{
		{"idle-only", []Phase{{Name: "idle", DurationSeconds: 1}}, 0, 0},
		{"ramps-and-idle", []Phase{{Name: "idle-before", DurationSeconds: 1}, {Name: "rise", DurationSeconds: 1, RateRPS: 4, RampSeconds: 1}, {Name: "fall", DurationSeconds: 1, FromRateRPS: 4, RampSeconds: 1}, {Name: "idle-after", DurationSeconds: 1}}, 400 * time.Millisecond, 4},
		{"final-drain", []Phase{{Name: "idle-before", DurationSeconds: 1}, {Name: "active", DurationSeconds: 1, RateRPS: 2}}, 800 * time.Millisecond, 2},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var calls atomic.Uint64
			var mu sync.Mutex
			var arrivals []float64
			c := testConfig("http://localhost/")
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if strings.HasPrefix(r.URL.Path, "/actuator/") {
					fmt.Fprint(w, `{"measurements":[{"statistic":"VALUE","value":0}]}`)
					return
				}
				calls.Add(1)
				mu.Lock()
				arrivals = append(arrivals, epoch(time.Now())-c.StartEpoch)
				mu.Unlock()
				time.Sleep(tc.delay)
				fmt.Fprint(w, "ok")
			}))
			defer srv.Close()
			c.Target = srv.URL
			c.Phases = tc.phases
			c = idleConfig(t, c)
			dir := t.TempDir()
			status, err := Run(context.Background(), c, dir)
			if tc.want == 0 {
				if err == nil || status.Outcome != "FAILED" || !strings.Contains(status.Error, "zero successful requests") {
					t.Fatalf("idle weakened zero-success failure rule %+v %v", status, err)
				}
			} else if err != nil || status.Outcome != "COMPLETE" {
				t.Fatalf("idle/ramp run failed %+v %v", status, err)
			}
			rows := readSamples(t, dir)
			s := totals(rows, "")
			assertAccounting(t, s)
			assertAccounting(t, status.Totals)
			if calls.Load() != tc.want || s.Offered != tc.want || s.Success != tc.want || s.Dropped != 0 || status.Totals.Offered != tc.want {
				t.Fatalf("HTTP/count conservation calls=%d %+v", calls.Load(), s)
			}
			for _, row := range rows {
				if strings.HasPrefix(row.Phase, "idle") && (row.Offered != 0 || row.Started != 0 || row.Completed != 0 || row.Dropped != 0) {
					t.Fatalf("idle phase generated traffic %+v", row)
				}
			}
			mu.Lock()
			defer mu.Unlock()
			for _, at := range arrivals {
				if at < 1 || (tc.name == "ramps-and-idle" && at >= 3) {
					t.Fatalf("HTTP request in idle interval at %v", at)
				}
			}
			_, horizon := compileSchedule(c)
			if status.ActualEnd < c.StartEpoch+horizon.Seconds() {
				t.Fatal("idle phases shortened scheduled run")
			}
			if tc.name == "final-drain" {
				late := false
				for _, row := range rows {
					if row.Phase == "active" && row.Completed > 0 && row.IntervalEndSec > 2 {
						late = true
					}
				}
				if !late || status.ActualEnd < c.StartEpoch+2.2 {
					t.Fatal("idle prefix lost final drain/original phase")
				}
			}
			b, err := os.ReadFile(filepath.Join(dir, "config.json"))
			if err != nil {
				t.Fatal(err)
			}
			var stored map[string]any
			if err := json.Unmarshal(b, &stored); err != nil {
				t.Fatal(err)
			}
			if stored["allow_idle"] != true {
				t.Fatal("idle opt-in not persisted")
			}
		})
	}
}

func readSamples(t *testing.T, dir string) []Sample {
	t.Helper()
	f, err := os.Open(filepath.Join(dir, "samples.ndjson"))
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	var out []Sample
	s := bufio.NewScanner(f)
	for s.Scan() {
		var row Sample
		if err := json.Unmarshal(s.Bytes(), &row); err != nil {
			t.Fatal(err)
		}
		assertIntervalAccounting(t, row)
		out = append(out, row)
	}
	if s.Err() != nil {
		t.Fatal(s.Err())
	}
	return out
}

func assertIntervalAccounting(t *testing.T, row Sample) {
	t.Helper()
	var bins uint64
	for _, count := range row.Histogram {
		bins += count
	}
	if row.Started+row.Dropped != row.Offered || bins != row.Completed || row.LatencyCount != row.Completed {
		t.Fatalf("inconsistent interval counters: %+v", row)
	}
	if row.IntervalStartSec < 0 || row.IntervalEndSec < row.IntervalStartSec || row.ElapsedSec != row.IntervalEndSec {
		t.Fatalf("invalid interval boundaries: %+v", row)
	}
}

func TestFinalCountsRequireEveryPlannedArrivalAndCompletion(t *testing.T) {
	good := Sample{Offered: 3, Started: 2, Dropped: 1, Completed: 2, Success: 1, HTTPErrors: 1, LatencyCount: 2}
	if err := validateFinalCounts(good, 3); err != nil {
		t.Fatal(err)
	}
	for name, change := range map[string]func(*Sample){
		"pending reservation":    func(s *Sample) { s.Offered--; s.Dropped-- },
		"missing classification": func(s *Sample) { s.Started-- },
		"unfinished request":     func(s *Sample) { s.Completed--; s.Success--; s.LatencyCount--; s.Inflight = 1 },
		"missing outcome":        func(s *Sample) { s.HTTPErrors-- },
		"missing latency":        func(s *Sample) { s.LatencyCount-- },
	} {
		t.Run(name, func(t *testing.T) {
			broken := good
			change(&broken)
			if validateFinalCounts(broken, 3) == nil {
				t.Fatalf("incomplete final counts accepted %+v", broken)
			}
		})
	}
}

func totals(rows []Sample, phase string) Sample {
	var s Sample
	for _, r := range rows {
		if phase != "" && phase != r.Phase {
			continue
		}
		s.Offered += r.Offered
		s.Started += r.Started
		s.Completed += r.Completed
		s.Success += r.Success
		s.HTTPErrors += r.HTTPErrors
		s.TransportErrors += r.TransportErrors
		s.Timeouts += r.Timeouts
		s.Dropped += r.Dropped
		s.LatencyCount += r.LatencyCount
		s.LatencySumUS += r.LatencySumUS
	}
	return s
}

func assertAccounting(t *testing.T, s Sample) {
	t.Helper()
	if s.Offered != s.Started+s.Dropped || s.Started != s.Completed || s.Completed != s.Success+s.HTTPErrors+s.TransportErrors+s.Timeouts || s.Completed != s.LatencyCount {
		t.Fatalf("lost accounting: %+v", s)
	}
}

func TestOpenLoopSlowServerAndOriginalPhase(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasPrefix(r.URL.Path, "/actuator/") {
			fmt.Fprint(w, `{"measurements":[]}`)
			return
		}
		time.Sleep(350 * time.Millisecond)
		fmt.Fprint(w, "ok")
	}))
	defer srv.Close()
	c := testConfig(srv.URL)
	c.MaxInflight = 2
	c.Phases = []Phase{{Name: "a", DurationSeconds: 1, RateRPS: 40}, {Name: "b", DurationSeconds: 1, RateRPS: 40}}
	dir := t.TempDir()
	status, err := Run(context.Background(), c, dir)
	if err != nil {
		t.Fatal(err)
	}
	if status.Outcome != "COMPLETE" {
		t.Fatalf("status=%+v", status)
	}
	if status.DropReasons.Capacity == 0 {
		t.Fatal("capacity drops not distinguished")
	}
	rows := readSamples(t, dir)
	for _, p := range []string{"a", "b"} {
		s := totals(rows, p)
		assertAccounting(t, s)
		if s.Offered != 40 || s.Dropped == 0 || s.Success == 0 {
			t.Fatalf("phase %s %+v", p, s)
		}
	}
	late := false
	for _, r := range rows {
		if r.Phase == "a" && r.ElapsedSec > 1 && r.Completed > 0 {
			late = true
		}
		var bins uint64
		for _, n := range r.Histogram {
			bins += n
		}
		if bins != r.LatencyCount {
			t.Fatal("histogram lost completion")
		}
		if r.ClientCPUPct < 0 || r.ClientCPUPct > 100 || math.IsNaN(r.ClientCPUPct) {
			t.Fatal("invalid normalized CPU")
		}
	}
	if !late {
		t.Fatal("late completion lost original phase")
	}
	if status.ActualEnd < status.ActualStart+2 {
		t.Fatal("run ended before horizon")
	}
	if _, err := os.Stat(filepath.Join(dir, "config.json")); err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile(filepath.Join(dir, "status.json"))
	if err != nil {
		t.Fatal(err)
	}
	var stored Status
	if json.Unmarshal(b, &stored) != nil || stored.Outcome != "COMPLETE" {
		t.Fatalf("status not stored: %s", b)
	}
}

func TestLateStartCountsAllIntendedArrivals(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { fmt.Fprint(w, `{"measurements":[]}`) }))
	defer srv.Close()
	c := testConfig(srv.URL)
	c.StartEpoch = epoch(time.Now().Add(-5 * time.Second))
	c.Phases = []Phase{{Name: "past", DurationSeconds: 1, RateRPS: 1000000}}
	dir := t.TempDir()
	started := time.Now()
	status, err := Run(context.Background(), c, dir)
	if err == nil || status.Outcome != "FAILED" {
		t.Fatal("zero successful run marked complete")
	}
	if status.DropReasons.Lateness != 1000000 || !strings.Contains(strings.Join(status.Warnings, " "), "late start") {
		t.Fatalf("late start hidden %+v", status)
	}
	s := totals(readSamples(t, dir), "")
	assertAccounting(t, s)
	if s.Offered != 1000000 || s.Dropped != 1000000 || s.LatencyCount != 0 {
		t.Fatalf("lateness masked arrivals %+v", s)
	}
	if time.Since(started) > time.Second {
		t.Fatal("backlog iterated one arrival at a time")
	}
}

func TestTimeoutHTTPErrorAndCancellation(t *testing.T) {
	t.Run("timeout", func(t *testing.T) {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if strings.HasPrefix(r.URL.Path, "/actuator/") {
				fmt.Fprint(w, `{}`)
				return
			}
			<-r.Context().Done()
		}))
		defer srv.Close()
		c := testConfig(srv.URL)
		c.MaxInflight = 1
		c.Phases[0].RateRPS = 1
		dir := t.TempDir()
		status, err := Run(context.Background(), c, dir)
		if err == nil || status.Outcome != "FAILED" {
			t.Fatal("timeout-only run completed")
		}
		s := totals(readSamples(t, dir), "")
		assertAccounting(t, s)
		if s.Timeouts != 1 || s.LatencySumUS < 1900000 {
			t.Fatalf("deadline latency wrong %+v", s)
		}
	})
	t.Run("http", func(t *testing.T) {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(503) }))
		defer srv.Close()
		c := testConfig(srv.URL)
		dir := t.TempDir()
		status, err := Run(context.Background(), c, dir)
		if err == nil || status.Outcome != "FAILED" {
			t.Fatal("HTTP-error-only run completed")
		}
		s := totals(readSamples(t, dir), "")
		assertAccounting(t, s)
		if s.HTTPErrors == 0 || s.TransportErrors != 0 {
			t.Fatalf("HTTP classification %+v", s)
		}
	})
	t.Run("cancel", func(t *testing.T) {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { fmt.Fprint(w, `{}`) }))
		defer srv.Close()
		c := testConfig(srv.URL)
		c.StartEpoch = epoch(time.Now().Add(-time.Second))
		c.Phases[0].DurationSeconds = 4
		ctx, cancel := context.WithCancel(context.Background())
		time.AfterFunc(150*time.Millisecond, cancel)
		dir := t.TempDir()
		status, err := Run(ctx, c, dir)
		if err == nil || status.Outcome != "FAILED" || status.ActualEnd >= c.StartEpoch+4 {
			t.Fatalf("cancellation completed %+v %v", status, err)
		}
		if status.DropReasons.Cancelled == 0 {
			t.Fatal("cancelled planned arrivals not distinguished")
		}
		s := totals(readSamples(t, dir), "")
		assertAccounting(t, s)
		if s.Offered != 80 || s.Dropped == 0 {
			t.Fatal("cancelled planned arrivals disappeared")
		}
	})
}

func TestActuatorTaggedMetricsAndExplicitErrors(t *testing.T) {
	var mu sync.Mutex
	seen := map[string]string{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		seen[r.URL.Path+"?"+r.URL.RawQuery] = r.URL.Query().Get("tag")
		mu.Unlock()
		if strings.HasSuffix(r.URL.Path, "jvm.gc.memory.promoted") {
			http.NotFound(w, r)
			return
		}
		fmt.Fprint(w, `{"name":"metric","measurements":[{"statistic":"VALUE","value":0.4}]}`)
	}))
	defer srv.Close()
	var buf bytes.Buffer
	if err := pollMetrics(context.Background(), testConfig(srv.URL+"/work?x=1"), json.NewEncoder(&buf), srv.Client()); err != nil {
		t.Fatal(err)
	}
	dec := json.NewDecoder(&buf)
	out := map[string]MetricSample{}
	for dec.More() {
		var row MetricSample
		if err := dec.Decode(&row); err != nil {
			t.Fatal(err)
		}
		out[row.Metric] = row
		if row.Timestamp <= 0 {
			t.Fatal("missing timestamp")
		}
	}
	if len(out) != 12 || len(out["process.cpu.usage"].Data) == 0 || out["jvm.gc.memory.promoted"].Error == "" {
		t.Fatalf("metrics not explicit %+v", out)
	}
	for _, name := range []string{"used", "committed", "max"} {
		path := "/actuator/metrics/jvm.memory." + name + "?tag=area%3Aheap"
		if seen[path] != "area:heap" || len(out["jvm.memory."+name+".heap"].Data) == 0 {
			t.Fatalf("wrong heap metric %s %+v", name, seen)
		}
	}
	if seen["/actuator/metrics/jvm.memory.used?tag=area%3Anonheap"] != "area:nonheap" {
		t.Fatal("nonheap tag missing")
	}
}

func TestExactCleanupRetriesAndNoCollections(t *testing.T) {
	var mu sync.Mutex
	attempts := map[string]int{}
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "DELETE" || r.Header.Get("Authorization") != "Bearer own-token" {
			t.Errorf("unsafe cleanup %s %s", r.Method, r.Header.Get("Authorization"))
			w.WriteHeader(403)
			return
		}
		mu.Lock()
		attempts[r.URL.Path]++
		n := attempts[r.URL.Path]
		mu.Unlock()
		switch r.URL.Path {
		case "/apis/batch/v1/namespaces/benchmark/jobs/own-job":
			if n == 1 {
				w.WriteHeader(503)
			} else {
				w.WriteHeader(200)
			}
		case "/api/v1/namespaces/benchmark/services/own-svc":
			w.WriteHeader(404)
		default:
			t.Errorf("unexpected cleanup path %s", r.URL.Path)
			w.WriteHeader(403)
		}
	}))
	defer srv.Close()
	c := Cleanup{Namespace: "benchmark", ServerJob: "own-job", ServerService: "own-svc"}
	out := cleanupOwnResources(context.Background(), c, srv.URL, "own-token", srv.Client())
	if len(out) != 2 || !out[0].Success || !out[1].Success || out[0].Attempts != 2 {
		t.Fatalf("cleanup %+v", out)
	}
	if len(attempts) != 2 {
		t.Fatal("cleanup reached extra resource")
	}
}

func TestSlowMetricsPollHasOneBoundedBudget(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		select {
		case <-r.Context().Done():
		case <-time.After(500 * time.Millisecond):
			fmt.Fprint(w, `{}`)
		}
	}))
	defer srv.Close()
	var buf bytes.Buffer
	start := time.Now()
	if err := pollMetrics(context.Background(), testConfig(srv.URL), json.NewEncoder(&buf), srv.Client()); err != nil {
		t.Fatal(err)
	}
	if time.Since(start) > 2500*time.Millisecond {
		t.Fatalf("slow metrics consumed %v: missed 10s cadence possible", time.Since(start))
	}
	dec := json.NewDecoder(&buf)
	var count, failed int
	for dec.More() {
		var row MetricSample
		if err := dec.Decode(&row); err != nil {
			t.Fatal(err)
		}
		count++
		if row.Error != "" {
			failed++
		}
	}
	if count != 12 || failed == 0 {
		t.Fatalf("poll budget hid missing metrics count=%d failed=%d", count, failed)
	}
}

func TestExistingResultsArePreserved(t *testing.T) {
	dir := t.TempDir()
	for _, name := range []string{"config.json", "status.json", "samples.ndjson", "metrics.ndjson"} {
		if err := os.WriteFile(filepath.Join(dir, name), []byte("original"), 0644); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := Run(context.Background(), testConfig("http://localhost/"), dir); err == nil {
		t.Fatal("reused results allowed")
	}
	for _, name := range []string{"config.json", "status.json", "samples.ndjson", "metrics.ndjson"} {
		b, err := os.ReadFile(filepath.Join(dir, name))
		if err != nil || string(b) != "original" {
			t.Fatalf("overwrote %s: %s %v", name, b, err)
		}
	}
}

func TestPlannedLatencyAndRedirectAreExplicit(t *testing.T) {
	var followed bool
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/redirect" {
			w.Header().Set("Location", "/other")
			w.WriteHeader(302)
			return
		}
		followed = true
		fmt.Fprint(w, "ok")
	}))
	defer srv.Close()
	client := newHTTPClient(1)
	defer client.CloseIdleConnections()
	stats := newCounters(1)
	performRequest(context.Background(), client, srv.URL+"/redirect", time.Now().Add(-time.Millisecond), 0, stats)
	s := stats.total
	assertAccounting(t, s)
	if s.HTTPErrors != 1 || s.LatencySumUS < 1000 || followed {
		t.Fatalf("planned latency or redirect accounting %+v followed=%v", s, followed)
	}
}

func TestTransportErrorAndCancelledCleanupStatus(t *testing.T) {
	t.Run("transport", func(t *testing.T) {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			h := w.(http.Hijacker)
			conn, _, err := h.Hijack()
			if err != nil {
				t.Error(err)
				return
			}
			conn.Close()
		}))
		defer srv.Close()
		stats := newCounters(1)
		client := newHTTPClient(1)
		defer client.CloseIdleConnections()
		performRequest(context.Background(), client, srv.URL, time.Now(), 0, stats)
		assertAccounting(t, stats.total)
		if stats.total.TransportErrors != 1 || stats.total.Timeouts != 0 {
			t.Fatalf("transport classified wrong %+v", stats.total)
		}
	})
	t.Run("cancel before start", func(t *testing.T) {
		c := testConfig("http://localhost/")
		c.StartEpoch = epoch(time.Now().Add(time.Hour))
		c.Cleanup = &Cleanup{Namespace: "benchmark", ServerJob: "own-job", ServerService: "own-svc"}
		ctx, cancel := context.WithCancel(context.Background())
		cancel()
		dir := t.TempDir()
		status, err := Run(ctx, c, dir)
		if err == nil || status.Outcome != "FAILED" || len(status.Cleanup) != 2 || status.Cleanup[0].Name != "own-job" || status.Cleanup[1].Name != "own-svc" {
			t.Fatalf("cancel lost cleanup/status %+v %v", status, err)
		}
		s := totals(readSamples(t, dir), "")
		assertAccounting(t, s)
		if s.Offered != 20 || s.Dropped != 20 {
			t.Fatalf("cancel lost scheduled arrivals %+v", s)
		}
	})
}

func TestActualDispatchRejectsDelayAndCancellationAcrossFlush(t *testing.T) {
	for _, cancelled := range []bool{false, true} {
		t.Run(fmt.Sprintf("cancelled=%v", cancelled), func(t *testing.T) {
			var calls atomic.Int64
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { calls.Add(1); fmt.Fprint(w, "ok") }))
			defer srv.Close()
			client := newHTTPClient(1)
			defer client.CloseIdleConnections()
			stats := newCounters(1)
			plans, _ := compileSchedule(testConfig(srv.URL))
			start := time.Now()
			cpu, err := cpuSeconds()
			if err != nil {
				t.Fatal(err)
			}
			var buf bytes.Buffer
			samp := sampler{stats: stats, plans: plans, start: start, enc: json.NewEncoder(&buf), lastCPU: cpu}
			if err := samp.flush(); err != nil {
				t.Fatal(err)
			}
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			// Hold the real accounting lock across the scheduling pause. A guard
			// before lock acquisition would still accept its stale dispatch time.
			stats.mu.Lock()
			planned := time.Now()
			ready, done := make(chan struct{}), make(chan struct{})
			go func() { close(ready); performRequest(ctx, client, srv.URL, planned, 0, stats); close(done) }()
			<-ready
			time.Sleep(25 * time.Millisecond)
			if cancelled {
				cancel()
			}
			stats.mu.Unlock()
			select {
			case <-done:
			case <-time.After(3 * time.Second):
				t.Fatal("dispatch decision did not finish")
			}
			if err := samp.flush(); err != nil {
				t.Fatal(err)
			}
			if calls.Load() != 0 {
				t.Fatalf("late/cancelled arrival reached HTTP server %d times", calls.Load())
			}
			dec := json.NewDecoder(&buf)
			var rows []Sample
			for dec.More() {
				var row Sample
				if err := dec.Decode(&row); err != nil {
					t.Fatal(err)
				}
				assertIntervalAccounting(t, row)
				rows = append(rows, row)
			}
			s := totals(rows, "")
			assertAccounting(t, s)
			if s.Offered != 1 || s.Dropped != 1 || s.Started != 0 || s.Completed != 0 || s.LatencySumUS != 0 {
				t.Fatalf("reservation rollback or false latency %+v", s)
			}
			if cancelled && stats.drops.Cancelled != 1 || !cancelled && stats.drops.Lateness != 1 {
				t.Fatalf("wrong actual dispatch drop reason %+v", stats.drops)
			}
		})
	}
}

func TestSamplerIntervalsShareBoundariesAndSkipEmptyZeroTail(t *testing.T) {
	c := testConfig("http://localhost/")
	c.Phases = []Phase{{Name: "a", DurationSeconds: 1, RateRPS: 1}, {Name: "b", DurationSeconds: 1, RateRPS: 1}}
	plans, _ := compileSchedule(c)
	stats := newCounters(2)
	start := time.Now()
	cpu, err := cpuSeconds()
	if err != nil {
		t.Fatal(err)
	}
	var buf bytes.Buffer
	// A previous idle wait must not dilute CPU for the first [0,0.5] interval.
	cutoff := start.Add(500 * time.Millisecond)
	samp := sampler{stats: stats, plans: plans, start: start, enc: json.NewEncoder(&buf), lastCPU: cpu - .01, now: func() time.Time { return cutoff }}
	stats.offer(0, 1, "", 0)
	if err := samp.flush(); err != nil {
		t.Fatal(err)
	}
	stats.complete(0, "success", time.Millisecond, 0)
	stats.offer(1, 1, "", 0)
	stats.complete(1, "http", 2*time.Millisecond, 0)
	cutoff = start.Add(1250 * time.Millisecond)
	if err := samp.flush(); err != nil {
		t.Fatal(err)
	}
	cutoff = start.Add(1500 * time.Millisecond)
	if err := samp.flush(); err != nil {
		t.Fatal(err)
	}
	before := buf.Len()
	if err := samp.flush(); err != nil {
		t.Fatal(err)
	}
	if buf.Len() != before {
		t.Error("empty zero-length tail duplicated a sample")
	}
	dec := json.NewDecoder(&buf)
	var rows []map[string]any
	for dec.More() {
		var row map[string]any
		if err := dec.Decode(&row); err != nil {
			t.Fatal(err)
		}
		rows = append(rows, row)
	}
	if len(rows) != 4 {
		t.Errorf("want first a, late a+current b, empty b: %+v", rows)
		if len(rows) < 4 {
			return
		}
	}
	for i, want := range [][2]float64{{0, .5}, {.5, 1.25}, {.5, 1.25}, {1.25, 1.5}} {
		lo, hasLo := rows[i]["interval_start_sec"].(float64)
		hi, hasHi := rows[i]["interval_end_sec"].(float64)
		if !hasLo || !hasHi || lo != want[0] || hi != want[1] || rows[i]["elapsed_sec"] != hi {
			t.Errorf("row %d wrong boundaries: %+v", i, rows[i])
		}
	}
	if rows[0]["client_cpu_pct"].(float64) < .009/.5/float64(runtime.NumCPU())*100 {
		t.Error("first CPU interval included idle waiting")
	}
	if rows[1]["phase"] != "a" || rows[2]["phase"] != "b" {
		t.Fatal("completion changed original phase")
	}
}

func TestSamplerCutoffIncludesEventInsertedDuringLockContention(t *testing.T) {
	stats := newCounters(1)
	plans, _ := compileSchedule(testConfig("http://localhost/"))
	start := time.Now()
	cpu, err := cpuSeconds()
	if err != nil {
		t.Fatal(err)
	}
	var buf bytes.Buffer
	samp := sampler{stats: stats, plans: plans, start: start, enc: json.NewEncoder(&buf), lastCPU: cpu}
	stats.mu.Lock()
	ready, done := make(chan struct{}), make(chan error, 1)
	go func() { close(ready); done <- samp.flush() }()
	<-ready
	// The flush cannot snapshot while we own the lock. An event inserted during
	// that contention must precede the cutoff, regardless of goroutine scheduling.
	eventAt := time.Now()
	stats.offerLocked(0, 1, "lateness", 0)
	stats.mu.Unlock()
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	var row Sample
	if err := json.Unmarshal(bytes.TrimSpace(buf.Bytes()), &row); err != nil {
		t.Fatal(err)
	}
	assertIntervalAccounting(t, row)
	if row.Offered != 1 || row.Dropped != 1 {
		t.Fatalf("contention event missing %+v", row)
	}
	if row.IntervalEndSec < eventAt.Sub(start).Seconds() || row.Timestamp < epoch(eventAt) {
		t.Fatalf("included event at %.9fs postdates cutoff %.9fs", eventAt.Sub(start).Seconds(), row.IntervalEndSec)
	}
}

func TestCleanupForbiddenDoesNotRetryAndTransientIsBounded(t *testing.T) {
	for _, code := range []int{403, 503} {
		t.Run(fmt.Sprint(code), func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(code) }))
			defer srv.Close()
			out := cleanupOwnResources(context.Background(), Cleanup{Namespace: "benchmark", ServerJob: "own-job", ServerService: "own-svc"}, srv.URL, "token", srv.Client())
			want := 1
			if code == 503 {
				want = 3
			}
			for _, r := range out {
				if r.Success || r.Attempts != want || r.Error == "" {
					t.Fatalf("cleanup unbounded or silent %+v", out)
				}
			}
		})
	}
}

// Run explicitly with -bench BenchmarkOpenLoopLoopback -benchtime=1x. This is a
// diagnostic smoke test, not a portable capacity gate: server and generator share
// the host. The extra phases exercise the full 97-phase scheduling configuration.
func BenchmarkOpenLoopLoopback(b *testing.B) {
	for _, rate := range []float64{5000, 15000, 30000} {
		b.Run(fmt.Sprintf("%.0fRPS", rate), func(b *testing.B) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if strings.HasPrefix(r.URL.Path, "/actuator/") {
					fmt.Fprint(w, `{"measurements":[{"statistic":"VALUE","value":0}]}`)
					return
				}
				fmt.Fprint(w, "ok")
			}))
			defer srv.Close()
			for i := 0; i < b.N; i++ {
				c := testConfig(srv.URL)
				c.MaxInflight = 512
				c.StartEpoch = epoch(time.Now().Add(100 * time.Millisecond))
				c.Phases = []Phase{{Name: "smoke", DurationSeconds: 2, RateRPS: rate}}
				for j := 1; j <= 96; j++ {
					c.Phases = append(c.Phases, Phase{Name: fmt.Sprintf("later-%d", j), DurationSeconds: 1, RateRPS: 1})
				}
				ctx, cancel := context.WithDeadline(context.Background(), time.Unix(0, int64((c.StartEpoch+2.05)*1e9)))
				dir := b.TempDir()
				status, err := Run(ctx, c, dir)
				cancel()
				if err == nil || status.Outcome != "FAILED" {
					b.Fatal("diagnostic cancellation must fail the full schedule")
				}
				f, err := os.Open(filepath.Join(dir, "samples.ndjson"))
				if err != nil {
					b.Fatal(err)
				}
				scan := bufio.NewScanner(f)
				var rows []Sample
				hist := map[int]uint64{}
				var cpu, lag float64
				for scan.Scan() {
					var row Sample
					if err := json.Unmarshal(scan.Bytes(), &row); err != nil {
						b.Fatal(err)
					}
					if row.Phase != "smoke" {
						continue
					}
					rows = append(rows, row)
					cpu = math.Max(cpu, row.ClientCPUPct)
					lag = math.Max(lag, row.MaxDispatchLagMS)
					for bin, n := range row.Histogram {
						hist[bin] += n
					}
				}
				f.Close()
				if scan.Err() != nil {
					b.Fatal(scan.Err())
				}
				s := totals(rows, "")
				if s.Offered != uint64(2*rate) || s.Started+s.Dropped != s.Offered || s.Completed != s.Started || s.Success == 0 {
					b.Fatalf("smoke lost traffic accounting %+v", s)
				}
				var p99 uint64
				for bin := 1; bin < 4096; bin++ {
					p99 += hist[bin]
					if p99 >= uint64(math.Ceil(float64(s.LatencyCount)*.99)) {
						b.ReportMetric(float64(histogramUpper(bin))/1000, "p99-ms")
						break
					}
				}
				b.ReportMetric(float64(s.Success)/2, "success/s")
				b.ReportMetric(float64(s.Dropped)/float64(s.Offered)*100, "dropped-%")
				b.ReportMetric(cpu, "max-process-CPU-%")
				b.ReportMetric(lag, "max-lag-ms")
			}
		})
	}
}
