#!/bin/bash
# Generate Elasticsearch Summary CSV with all metrics
cd /home/ec2-user/benchmark/results

echo "Processing Elasticsearch..."

# Header
echo "instance,cold_start_avg,cold_start_std,seq_index_avg,seq_index_std,bulk_index_avg,bulk_index_std,search_match_all_avg,search_match_all_std,search_term_avg,search_term_std,gc_time_avg,gc_time_std" > elasticsearch/summary.csv

for dir in elasticsearch/*/; do
  instance=$(basename "$dir")
  [ "$instance" = "summary.csv" ] && continue
  [ ! -d "$dir" ] && continue

  if [ -f "${dir}run1.log" ]; then
    # Use temp files for each metric
    tmpfile=$(mktemp)

    # Extract all metrics from all runs
    cs_vals=$(grep "^COLD_START_MS:" "${dir}"run*.log 2>/dev/null | awk -F: '{print $NF}' | tr -d ' ' | tr '\n' ' ')
    si_vals=$(grep "^SEQUENTIAL_INDEX_100_MS:" "${dir}"run*.log 2>/dev/null | awk -F: '{print $NF}' | tr -d ' ' | tr '\n' ' ')
    bi_vals=$(grep "^BULK_INDEX_1000_MS:" "${dir}"run*.log 2>/dev/null | awk -F: '{print $NF}' | tr -d ' ' | tr '\n' ' ')
    sa_vals=$(grep "MATCH_ALL_AVG_MS:" "${dir}"run*.log 2>/dev/null | awk -F: '{print $NF}' | tr -d ' ' | tr '\n' ' ')
    st_vals=$(grep "TERM_AVG_MS:" "${dir}"run*.log 2>/dev/null | awk -F: '{print $NF}' | tr -d ' ' | tr '\n' ' ')
    gc_vals=$(grep "^GC_TIME_DURING_TEST_MS:" "${dir}"run*.log 2>/dev/null | awk -F: '{print $NF}' | tr -d ' ' | tr '\n' ' ')

    # Calculate stats using awk
    calc_stats() {
      local vals="$1"
      if [ -z "$vals" ] || [ "$vals" = " " ]; then
        echo "0.00,0.00"
        return
      fi
      echo "$vals" | awk '{
        n=0; sum=0; sum2=0
        for(i=1;i<=NF;i++) {
          if($i+0 == $i) { n++; sum+=$i; sum2+=$i*$i }
        }
        if(n>0) {
          avg=sum/n
          if(n>1) std=sqrt((sum2-sum*sum/n)/(n-1)); else std=0
          printf "%.2f,%.2f", avg, std
        } else {
          print "0.00,0.00"
        }
      }'
    }

    cs_stats=$(calc_stats "$cs_vals")
    si_stats=$(calc_stats "$si_vals")
    bi_stats=$(calc_stats "$bi_vals")
    sa_stats=$(calc_stats "$sa_vals")
    st_stats=$(calc_stats "$st_vals")
    gc_stats=$(calc_stats "$gc_vals")

    echo "${instance},${cs_stats},${si_stats},${bi_stats},${sa_stats},${st_stats},${gc_stats}" >> elasticsearch/summary.csv
    rm -f "$tmpfile"
  fi
done

echo ""
echo "=== Elasticsearch Summary Generated ==="
head -10 elasticsearch/summary.csv
echo ""
echo "Total rows: $(wc -l < elasticsearch/summary.csv)"
