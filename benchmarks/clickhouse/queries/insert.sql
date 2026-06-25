-- INSERT 처리량 테스트
-- 실행 순서상 43쿼리 5세트 측정 이후에 실행 (테이블 행수가 변경되므로).
-- INSERT_ROWS placeholder = 삽입 행 수 (기본 10000000). 실행 스크립트가 치환.
INSERT INTO hits SELECT * FROM hits LIMIT INSERT_ROWS;
