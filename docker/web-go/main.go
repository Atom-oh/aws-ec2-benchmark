// Go net/http (stdlib) — web framework benchmark. GOMAXPROCS defaults to the cgroup CPU quota
// / host vCPUs (Go >= 1.25 is cgroup-aware), so one process uses all 4 vCPUs.
// Endpoint spec shared with docker/web-*/.
package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"runtime"
)

const rounds = 2000

var seed = []byte("benchmark-seed")

func main() {
	version := fmt.Sprintf("go %s net/http GOMAXPROCS %d", runtime.Version(), runtime.GOMAXPROCS(0))
	mux := http.NewServeMux()
	mux.HandleFunc("GET /plaintext", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain")
		w.Write([]byte("Hello, World!"))
	})
	mux.HandleFunc("GET /json", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"message": "Hello, World!"})
	})
	mux.HandleFunc("GET /compute", func(w http.ResponseWriter, r *http.Request) {
		h := seed
		for i := 0; i < rounds; i++ {
			s := sha256.Sum256(h)
			h = s[:]
		}
		w.Header().Set("Content-Type", "text/plain")
		w.Write([]byte(hex.EncodeToString(h)))
	})
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) { w.Write([]byte("ok")) })
	mux.HandleFunc("GET /version", func(w http.ResponseWriter, r *http.Request) { w.Write([]byte(version)) })
	log.Fatal(http.ListenAndServe(":8080", mux))
}
