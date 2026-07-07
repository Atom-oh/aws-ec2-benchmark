// 공통 navbar 주입. 새 리포트 추가 시 이 배열에 1줄만 추가하면 11개 파일을 손대지 않고 전체 메뉴에 반영된다.
// 사용법: 각 report HTML의 <head>에 `<script src="report-nav.js" defer></script>` 추가.
(function () {
    var REPORTS = [
        { file: 'geekbench-report.html', name: 'Geekbench' },
        { file: 'passmark-report.html', name: 'PassMark' },
        { file: 'sysbench-report.html', name: 'Sysbench' },
        { file: 'stress-ng-report.html', name: 'stress-ng' },
        { file: 'iperf3-report.html', name: 'iperf3' },
        { file: 'redis-report.html', name: 'Redis' },
        { file: 'nginx-report.html', name: 'Nginx' },
        { file: 'springboot-report.html', name: 'SpringBoot' },
        { file: 'elasticsearch-report.html', name: 'Elasticsearch' },
        { file: 'clickhouse-report.html', name: 'ClickHouse' },
        { file: 'kafka-report.html', name: 'Kafka' },
    ];

    var current = location.pathname.split('/').pop();
    var links = REPORTS.map(function (r) {
        var active = r.file === current ? ' class="active"' : '';
        return '<a href="' + r.file + '"' + active + '>' + r.name + '</a>';
    }).join('');

    var nav = document.createElement('nav');
    nav.className = 'navbar';
    nav.innerHTML =
        '<div class="navbar-container">' +
        '<a href="../index.html" class="navbar-brand">EC2 Benchmark</a>' +
        '<div class="navbar-links">' + links + '</div>' +
        '</div>';

    document.body.insertBefore(nav, document.body.firstChild);
})();
