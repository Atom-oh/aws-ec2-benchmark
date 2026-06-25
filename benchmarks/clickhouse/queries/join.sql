-- self-JOIN 테스트: hits를 자신의 RegionID 집계와 조인
-- (ClickBench 표준에는 JOIN이 없으므로 대표 self-JOIN을 정의)
--
-- 큰 좌변(전체 hits) ⋈ 작은 우변(RegionID별 집계) → join 엔진 + group by 경로를 측정.
-- OOM 방지(소메모리 8GB 인스턴스): grace_hash + RAM-상대 spill 임계값.
--   SPILL_BYTES / MAX_MEM_BYTES placeholder는 실행 스크립트가 /proc/meminfo 기반으로
--   RAM 비율(예: group by spill 50%, max_memory 80%)을 바이트로 계산해 치환한다.
--   → 모든 인스턴스에서 RAM 상대값으로 동작하여 공정 비교 (절대 바이트 하드코딩 금지).
SELECT h.RegionID, r.cnt AS region_total, COUNT(*) AS matched
FROM hits AS h
INNER JOIN (SELECT RegionID, COUNT(*) AS cnt FROM hits GROUP BY RegionID) AS r
  ON h.RegionID = r.RegionID
WHERE h.SearchPhrase <> ''
GROUP BY h.RegionID, r.cnt
ORDER BY matched DESC
LIMIT 20
SETTINGS join_algorithm = 'grace_hash', max_bytes_before_external_group_by = SPILL_BYTES, max_memory_usage = MAX_MEM_BYTES;
