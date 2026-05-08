from flask import Flask, request, jsonify, render_template, send_file
from flask_cors import CORS
import yfinance as yf
import pandas as pd
import numpy as np
import io
import os

app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app)

# 데이터 캐싱을 위한 딕셔너리
data_cache = {}

def get_data(ticker_symbol="TQQQ"):
    global data_cache
    ticker_symbol = ticker_symbol.upper()
    
    if ticker_symbol not in data_cache:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="max")
        if df.empty:
            return None
        df.index = df.index.tz_localize(None)
        data = df[['Open', 'Close']].copy()
        data['Monthly_End'] = data.index.is_month_end
        data_cache[ticker_symbol] = data
        
    return data_cache[ticker_symbol]

def run_backtest(params):
    ticker_symbol = params.get('ticker', 'TQQQ').upper()
    data = get_data(ticker_symbol)
    if data is None or data.empty:
        return {'error': f'{ticker_symbol} 데이터를 찾을 수 없습니다.'}
    full_df = data.copy()
    
    start_date_str = params.get('startDate')
    if start_date_str:
        df = full_df[full_df.index >= start_date_str].copy()
    else:
        df = full_df.copy()

    if df.empty:
        return {'error': '선택한 날짜 이후의 데이터가 없습니다.'}

    investment_type = params.get('investmentType', 'lump_sum')
    initial_amount = float(params.get('initialAmount', 10000))
    monthly_amount = float(params.get('monthlyAmount', 1000))
    stop_loss = float(params.get('stopLoss', 0)) / 100
    take_profit = float(params.get('takeProfit', 0)) / 100
    
    # 결과 저장용 리스트
    dates = []
    portfolio_values = []
    invested_amounts = []
    opens = []
    closes = []
    cash = 0.0
    shares = 0.0
    total_invested = 0.0
    
    peak_value = 0.0
    
    # 첫 거래일
    first_day = True
    current_month = -1
    
    for date, row in df.iterrows():
        price = row['Close']
        open_p = row['Open']
        
        # 투자 로직
        if first_day:
            shares += initial_amount / price
            total_invested += initial_amount
            first_day = False
            current_month = date.month
        elif investment_type == 'dca' and date.month != current_month:
            shares += monthly_amount / price
            total_invested += monthly_amount
            current_month = date.month
            
        current_value = shares * price + cash
        
        if current_value > peak_value:
            peak_value = current_value
            
        # 손절/익절 로직
        if shares > 0:
            current_return = (current_value - total_invested) / total_invested if total_invested > 0 else 0
            sold = False
            if take_profit > 0 and current_return >= take_profit:
                cash += shares * price
                shares = 0
                sold = True
            elif stop_loss > 0 and current_return <= -stop_loss:
                cash += shares * price
                shares = 0
                sold = True
                
        dates.append(date)
        portfolio_values.append(current_value)
        invested_amounts.append(total_invested)
        opens.append(open_p)
        closes.append(price)

    result_df = pd.DataFrame({
        'Date': dates,
        'PortfolioValue': portfolio_values,
        'InvestedAmount': invested_amounts,
        'Open': opens,
        'Close': closes
    })

    # 일별 데이터 계산 보강
    result_df['Prev_Value'] = result_df['PortfolioValue'].shift(1).fillna(initial_amount)
    result_df['Daily_Return'] = (result_df['PortfolioValue'] - result_df['Prev_Value']) / result_df['Prev_Value']
    result_df['Cumulative_Return'] = (result_df['PortfolioValue'] - result_df['InvestedAmount']) / result_df['InvestedAmount']
    
    # 일별 MDD (당일 시가 대비 종가 하락분만 계산, 상승 시 0)
    # PortfolioValue는 종가 기준이므로, 시가 기준 가치를 계산해야 함
    # 시가 기준 가치 = (shares * row['Open'] + cash)
    # 여기서는 간단히 (Close - Open) / Open 으로 계산 (수수료 등 제외)
    result_df['Daily_MDD'] = (result_df['Close'] - result_df['Open']) / result_df['Open']
    result_df['Daily_MDD'] = result_df['Daily_MDD'].apply(lambda x: min(0, x))
    
    # 누적 MDD (전체 기간 중 현재까지의 최저 Drawdown)
    result_df['Peak'] = result_df['PortfolioValue'].cummax()
    result_df['Drawdown'] = (result_df['PortfolioValue'] - result_df['Peak']) / result_df['Peak']
    result_df['Cumulative_Peak_MDD'] = result_df['Drawdown'].cummin()
    mdd = result_df['Drawdown'].min()
    
    # 월별 통계 계산
    result_df['YearMonth'] = result_df['Date'].dt.to_period('M')
    
    # 월간 내 로컬 전고점 및 낙폭 계산
    result_df['Monthly_Local_Peak'] = result_df.groupby('YearMonth')['PortfolioValue'].cummax()
    result_df['Monthly_Local_Drawdown'] = (result_df['PortfolioValue'] - result_df['Monthly_Local_Peak']) / result_df['Monthly_Local_Peak']
    result_df['Monthly_Peak_MDD'] = result_df.groupby('YearMonth')['Monthly_Local_Drawdown'].cummin()
    
    monthly_groups = result_df.groupby('YearMonth')
    
    monthly_stats = []
    for name, group in monthly_groups:
        # 해당 월의 마지막 날 가치
        end_val = group['PortfolioValue'].iloc[-1]
        # 해당 월의 첫날 직전 가치 (전월 말 가치)
        # 만약 전월 데이터가 없으면 초기 투자금(initial_amount) 또는 첫날 PortfolioValue 사용
        first_day_idx = group.index[0]
        if first_day_idx > 0:
            prev_month_end_val = result_df['PortfolioValue'].iloc[first_day_idx - 1]
        else:
            # 첫 거래일의 경우, 투자 원금 대비로 계산
            prev_month_end_val = group['InvestedAmount'].iloc[0]
            
        m_return = (end_val - prev_month_end_val) / prev_month_end_val if prev_month_end_val > 0 else 0
        total_invested_at_end = group['InvestedAmount'].iloc[-1]
        c_return = (end_val - total_invested_at_end) / total_invested_at_end
        
        # 월간 MDD (해당 월 내 최고점 대비 로컬 MDD)
        group_peak = group['PortfolioValue'].cummax()
        group_dd = (group['PortfolioValue'] - group_peak) / group_peak
        m_mdd_local = group_dd.min()
        
        # 누적 MDD (투자 시작일부터 해당 월말까지 중 최고 낙폭)
        c_mdd = group['Cumulative_Peak_MDD'].iloc[-1]
        
        monthly_stats.append({
            'Month': str(name),
            'Open': float(group['Open'].iloc[0]),
            'Close': float(group['Close'].iloc[-1]),
            'MonthlyReturn': float(m_return * 100),
            'CumulativeReturn': float(c_return * 100),
            'MonthlyMDD': float(m_mdd_local * 100),
            'CumulativeMDD': float(group['Cumulative_Peak_MDD'].iloc[-1] * 100)
        })

    # JSON 응답용 날짜 변환 및 필드 정리
    result_df['Date_Str'] = result_df['Date'].dt.strftime('%Y-%m-%d')
    daily_stats = []
    for _, row in result_df.iterrows():
        daily_stats.append({
            'Date': row['Date_Str'],
            'Open': float(row['Open']),
            'Close': float(row['Close']),
            'DailyReturn': float(row['Daily_Return'] * 100),
            'CumulativeReturn': float(row['Cumulative_Return'] * 100),
            'DailyMDD': float(row['Daily_MDD'] * 100),
            'MonthlyMDD': float(row['Monthly_Peak_MDD'] * 100),
            'CumulativeMDD': float(row['Cumulative_Peak_MDD'] * 100)
        })
    
    return {
        'timeseries': result_df[['Date_Str', 'PortfolioValue', 'InvestedAmount', 'Drawdown', 'Daily_MDD']].rename(columns={'Date_Str':'Date'}).to_dict('records'),
        'daily_report': daily_stats,
        'monthly_report': monthly_stats,
        'summary': {
            'finalValue': float(result_df['PortfolioValue'].iloc[-1]),
            'totalInvested': float(result_df['InvestedAmount'].iloc[-1]),
            'totalReturn': float(result_df['Cumulative_Return'].iloc[-1] * 100),
            'cagr': float(((result_df['PortfolioValue'].iloc[-1] / result_df['InvestedAmount'].iloc[-1]) ** (1 / ((result_df['Date'].iloc[-1] - result_df['Date'].iloc[0]).days / 365.25)) - 1) * 100) if result_df['InvestedAmount'].iloc[-1] > 0 else 0,
            'mdd': float(mdd * 100)
        }
    }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/info')
def api_info():
    ticker_symbol = request.args.get('ticker', 'TQQQ').upper()
    df = get_data(ticker_symbol)
    if df is None:
        return jsonify({'error': '데이터 없음'}), 404
    return jsonify({
        'start_date': df.index.min().strftime('%Y-%m-%d'),
        'end_date': df.index.max().strftime('%Y-%m-%d')
    })

@app.route('/api/backtest', methods=['POST'])
def api_backtest():
    params = request.json
    try:
        results = run_backtest(params)
        if 'error' in results:
            return jsonify(results), 400
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/download', methods=['POST'])
def api_download():
    params = request.json
    try:
        results = run_backtest(params)
        df_daily = pd.DataFrame(results['daily_report'])
        df_monthly = pd.DataFrame(results['monthly_report'])
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_daily.to_excel(writer, index=False, sheet_name='Daily Report')
            df_monthly.to_excel(writer, index=False, sheet_name='Monthly Report')
        
        output.seek(0)
        return send_file(
            output,
            download_name='tqqq_backtest_results.xlsx',
            as_attachment=True,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 400

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
