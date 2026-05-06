document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('simulation-form');
    const investmentType = document.getElementById('investmentType');
    const monthlyAmountGroup = document.getElementById('monthlyAmountGroup');
    const downloadBtn = document.getElementById('downloadBtn');
    const loader = document.getElementById('loader');
    
    let chartInstance = null;
    let currentParams = null;

    const tickerInput = document.getElementById('ticker');

    // Initialize date range
    async function initDateRange(ticker = 'TQQQ') {
        try {
            const response = await fetch(`/api/info?ticker=${ticker}`);
            if (!response.ok) return;
            const data = await response.json();
            const startInput = document.getElementById('startDate');
            startInput.min = data.start_date;
            startInput.max = data.end_date;
            if (!startInput.value || startInput.value < data.start_date) {
                startInput.value = data.start_date;
            }
        } catch (error) {
            console.error('Failed to load date info', error);
        }
    }
    initDateRange(tickerInput.value);

    // Refresh date range when ticker changes
    tickerInput.addEventListener('blur', () => {
        initDateRange(tickerInput.value);
    });

    // Toggle Monthly Amount input
    investmentType.addEventListener('change', (e) => {
        if (e.target.value === 'dca') {
            monthlyAmountGroup.style.display = 'block';
        } else {
            monthlyAmountGroup.style.display = 'none';
        }
    });

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        currentParams = {
            ticker: tickerInput.value.toUpperCase(),
            startDate: document.getElementById('startDate').value,
            investmentType: investmentType.value,
            initialAmount: document.getElementById('initialAmount').value,
            monthlyAmount: document.getElementById('monthlyAmount').value,
            stopLoss: document.getElementById('stopLoss').value,
            takeProfit: document.getElementById('takeProfit').value
        };

        loader.style.display = 'flex';
        downloadBtn.disabled = true;

        try {
            const response = await fetch('/api/backtest', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(currentParams)
            });

            if (!response.ok) throw new Error('백테스트 실패');
            
            const data = await response.json();
            updateUI(data);
            downloadBtn.disabled = false;
        } catch (error) {
            alert('오류가 발생했습니다: ' + error.message);
        } finally {
            loader.style.display = 'none';
        }
    });

    downloadBtn.addEventListener('click', async () => {
        if (!currentParams) return;
        
        loader.style.display = 'flex';
        try {
            const response = await fetch('/api/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(currentParams)
            });
            
            if (!response.ok) throw new Error('다운로드 실패');
            
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'tqqq_backtest_results.xlsx';
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            a.remove();
        } catch (error) {
            alert('오류: ' + error.message);
        } finally {
            loader.style.display = 'none';
        }
    });

    function updateUI(data) {
        const { summary, timeseries, daily_report, monthly_report } = data;
        
        // Update summary cards
        document.getElementById('res-final-value').textContent = '$' + summary.finalValue.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
        document.getElementById('res-total-invested').textContent = '$' + summary.totalInvested.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
        
        const returnText = summary.totalReturn.toFixed(2) + '%';
        document.getElementById('res-total-return').textContent = returnText;
        document.getElementById('res-total-return').style.color = summary.totalReturn >= 0 ? 'var(--neon-green)' : 'var(--neon-pink)';
        
        document.getElementById('res-cagr').textContent = summary.cagr.toFixed(2) + '%';
        document.getElementById('res-mdd').textContent = summary.mdd.toFixed(2) + '%';

        drawChart(timeseries);
        renderDailyTable(daily_report);
        renderMonthlyTable(monthly_report);
    }

    function renderDailyTable(stats) {
        const tbody = document.getElementById('daily-table-body');
        tbody.innerHTML = '';
        
        stats.slice().reverse().forEach(item => {
            const row = document.createElement('tr');
            const returnClass = item.DailyReturn >= 0 ? 'positive' : 'negative';
            const cumReturnClass = item.CumulativeReturn >= 0 ? 'positive' : 'negative';
            
            row.innerHTML = `
                <td>${item.Date}</td>
                <td>${item.Open.toFixed(2)}</td>
                <td>${item.Close.toFixed(2)}</td>
                <td class="${returnClass}">${item.DailyReturn.toFixed(2)}%</td>
                <td class="${cumReturnClass}">${item.CumulativeReturn.toFixed(2)}%</td>
                <td class="negative">${item.DailyMDD.toFixed(2)}%</td>
                <td class="negative">${item.MonthlyMDD.toFixed(2)}%</td>
                <td class="negative">${item.CumulativeMDD.toFixed(2)}%</td>
            `;
            tbody.appendChild(row);
        });
    }

    function renderMonthlyTable(stats) {
        const tbody = document.getElementById('monthly-table-body');
        tbody.innerHTML = '';
        
        stats.slice().reverse().forEach(item => {
            const row = document.createElement('tr');
            
            const mReturnClass = item.MonthlyReturn >= 0 ? 'positive' : 'negative';
            const cReturnClass = item.CumulativeReturn >= 0 ? 'positive' : 'negative';
            
            row.innerHTML = `
                <td>${item.Month}</td>
                <td>${item.Open.toFixed(2)}</td>
                <td>${item.Close.toFixed(2)}</td>
                <td class="${mReturnClass}">${item.MonthlyReturn.toFixed(2)}%</td>
                <td class="${cReturnClass}">${item.CumulativeReturn.toFixed(2)}%</td>
                <td class="negative">${item.MonthlyMDD.toFixed(2)}%</td>
                <td class="negative">${item.CumulativeMDD.toFixed(2)}%</td>
            `;
            tbody.appendChild(row);
        });
    }

    function drawChart(timeseries) {
        const ctx = document.getElementById('performanceChart').getContext('2d');
        const ticker = tickerInput.value.toUpperCase();
        
        if (chartInstance) {
            chartInstance.destroy();
        }

        const labels = timeseries.map(d => d.Date);
        const portfolioData = timeseries.map(d => d.PortfolioValue);
        const investedData = timeseries.map(d => d.InvestedAmount);
        const drawdownData = timeseries.map(d => d.Drawdown * 100);
        const dailyDrawdownData = timeseries.map(d => d.Daily_MDD * 100);

        // Chart.js defaults for dark theme
        Chart.defaults.color = '#c5c6c7';
        Chart.defaults.font.family = 'Inter';

        chartInstance = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: `${ticker} 포트폴리오 자산 ($)`,
                        data: portfolioData,
                        borderColor: '#66fcf1',
                        backgroundColor: 'rgba(102, 252, 241, 0.1)',
                        borderWidth: 2,
                        pointRadius: 0,
                        pointHoverRadius: 4,
                        fill: true,
                        tension: 0.1,
                        yAxisID: 'y'
                    },
                    {
                        label: '누적 투자원금 ($)',
                        data: investedData,
                        borderColor: '#ff007f',
                        borderDash: [5, 5],
                        borderWidth: 2,
                        pointRadius: 0,
                        fill: false,
                        tension: 0.1,
                        yAxisID: 'y'
                    },
                    {
                        label: '누적 하락폭 (Cumulative MDD %)',
                        data: drawdownData,
                        borderColor: 'rgba(255, 0, 127, 0.4)',
                        backgroundColor: 'rgba(255, 0, 127, 0.1)',
                        borderWidth: 1,
                        pointRadius: 0,
                        fill: true,
                        tension: 0.1,
                        yAxisID: 'y1'
                    },
                    {
                        label: '일별 하락폭 (Daily MDD %)',
                        data: dailyDrawdownData,
                        borderColor: 'rgba(102, 252, 241, 0.5)',
                        borderWidth: 1,
                        pointRadius: 0,
                        fill: false,
                        tension: 0.1,
                        yAxisID: 'y1'
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false,
                },
                plugins: {
                    legend: {
                        position: 'top',
                    },
                    tooltip: {
                        backgroundColor: 'rgba(11, 12, 16, 0.9)',
                        titleColor: '#66fcf1',
                        bodyColor: '#fff',
                        borderColor: '#45a29e',
                        borderWidth: 1,
                        callbacks: {
                            label: function(context) {
                                let label = context.dataset.label || '';
                                if (label) label += ': ';
                                if (context.datasetIndex >= 2) {
                                    label += context.parsed.y.toFixed(2) + '%';
                                } else {
                                    label += '$' + context.parsed.y.toLocaleString();
                                }
                                return label;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: { maxTicksLimit: 10 }
                    },
                    y: {
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        type: 'logarithmic',
                        position: 'left',
                        ticks: {
                            callback: function(value, index, values) {
                                return '$' + value.toLocaleString();
                            }
                        }
                    },
                    y1: {
                        type: 'linear',
                        display: true,
                        position: 'right',
                        min: -100,
                        max: 0,
                        grid: { drawOnChartArea: false },
                        ticks: {
                            callback: function(value) {
                                return value + '%';
                            }
                        },
                        title: {
                            display: true,
                            text: 'Drawdown (%)',
                            color: 'rgba(255, 0, 127, 0.7)'
                        }
                    }
                }
            }
        });
    }
});
