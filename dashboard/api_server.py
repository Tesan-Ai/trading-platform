import json
import csv
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from database import get_observability_store

REPORT_PATH = "research_results_orvwap/orvwap_report.json"
MULTI_STRATEGY_REPORT_PATH = "research_results/multi_strategy/latest_multi_strategy_report.json"
MULTI_STRATEGY_LEADERBOARD_PATH = "research_results/multi_strategy/multi_strategy_leaderboard.csv"
SWEEP_JSON_PATH = "research_results_orvwap/orvwap_parameter_sweep.json"
SWEEP_CSV_PATH = "research_results_orvwap/orvwap_parameter_sweep.csv"


TABLE_BY_PATH = {
    "/api/signals": "signals",
    "/api/trades": "trades",
    "/api/positions": "positions",
    "/api/risk-events": "risk_events",
    "/api/logs": "bot_logs",
    "/api/settings": "bot_settings",
    "/api/ai-explanations": "ai_explanations",
    "/api/ai-reviews": "ai_explanations",
}


def _rows(table: str, limit: int = 100, decision_type: str | None = None) -> list[dict]:
    order_column = "timestamp"
    if table == "positions":
        order_column = "updated_at"
    elif table == "bot_settings":
        order_column = "updated_at"
    elif table == "ai_explanations":
        order_column = "created_at"

    with get_observability_store().connect() as connection:
        where = ""
        params = []
        if table == "ai_explanations" and decision_type is not None:
            where = "where decision_type = ?"
            params.append(decision_type)
        params.append(limit)
        rows = connection.execute(
            f"select * from {table} {where} order by {order_column} desc limit ?",
            tuple(params),
        ).fetchall()
        return [dict(row) for row in rows]


def _status() -> dict:
    with get_observability_store().connect() as connection:
        run = connection.execute("select * from bot_runs order by id desc limit 1").fetchone()
        heartbeat = connection.execute("select * from bot_heartbeats order by id desc limit 1").fetchone()
        signal = connection.execute("select * from signals order by id desc limit 1").fetchone()
        trade = connection.execute("select * from trades order by id desc limit 1").fetchone()
        risk = connection.execute("select * from risk_events order by id desc limit 1").fetchone()
        ai = connection.execute("select * from ai_explanations order by id desc limit 1").fetchone()
        settings = connection.execute("select * from bot_settings where id = 1").fetchone()
        open_positions = connection.execute("select count(*) as count from positions").fetchone()
        trades_today = connection.execute("select count(*) as count from trades where date(timestamp) = date('now')").fetchone()
        signals_today = connection.execute("select count(*) as count from signals where date(timestamp) = date('now')").fetchone()
        return {
            "bot_status": dict(run) if run else None,
            "latest_heartbeat": dict(heartbeat) if heartbeat else None,
            "current_mode": "PAPER",
            "live_trading_disabled": True,
            "settings": dict(settings) if settings else None,
            "open_positions": open_positions["count"] if open_positions else 0,
            "trades_today": trades_today["count"] if trades_today else 0,
            "signals_today": signals_today["count"] if signals_today else 0,
            "latest_signal": dict(signal) if signal else None,
            "latest_trade": dict(trade) if trade else None,
            "latest_risk_block": dict(risk) if risk else None,
            "latest_ai_explanation": dict(ai) if ai else None,
        }


def _load_json_file(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def _load_sweep_results() -> list[dict]:
    data = _load_json_file(SWEEP_JSON_PATH, {"results": []})
    if isinstance(data, dict):
        return data.get("results", [])
    return []


def _load_trade_rows() -> list[dict]:
    path = "logs/orvwap_signals.csv"
    if not os.path.exists(path):
        return []
    return []


def _html_report() -> bytes:
    body = """
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>ORVWAP Strategy Report</title>
        <style>
          :root { --bg:#f4f1ea; --surface:#fff; --soft:#f8faf8; --ink:#172026; --muted:#66737c; --line:#d7ddd8; --green:#13795b; --red:#b42318; --amber:#9a6700; --blue:#176b87; }
          * { box-sizing:border-box; }
          body { margin:0; background:var(--bg); color:var(--ink); font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
          header { background:#fff; border-bottom:1px solid var(--line); position:sticky; top:0; z-index:5; }
          .top { max-width:1440px; margin:0 auto; padding:16px 24px; display:flex; justify-content:space-between; gap:16px; align-items:center; }
          h1 { margin:0; font-size:21px; } h2 { margin:0; font-size:16px; } h3 { margin:0 0 8px; font-size:14px; }
          .sub { color:var(--muted); font-size:13px; margin-top:4px; }
          main { max-width:1440px; margin:0 auto; padding:20px 24px 48px; }
          .pill { display:inline-flex; align-items:center; height:30px; padding:0 10px; border:1px solid var(--line); background:var(--soft); font-weight:800; font-size:12px; }
          .pill.good { color:var(--green); background:#e9fbf4; border-color:#b8e3d4; } .pill.bad { color:var(--red); background:#fff7f5; border-color:#f0c7c2; } .pill.warn { color:var(--amber); background:#fff8df; border-color:#efd59a; }
          .banner { border:1px solid #f0c7c2; background:#fff7f5; color:var(--red); padding:12px 14px; font-weight:750; margin-bottom:16px; display:flex; justify-content:space-between; gap:12px; }
          .actions { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }
          button, a.button { border:1px solid var(--line); background:#fff; color:var(--ink); height:34px; padding:0 12px; cursor:pointer; font-weight:700; text-decoration:none; display:inline-flex; align-items:center; }
          .cards { display:grid; grid-template-columns:repeat(5, minmax(0,1fr)); gap:12px; margin-bottom:16px; }
          .card, .panel { background:var(--surface); border:1px solid var(--line); }
          .card { padding:14px; min-height:96px; } .card label { display:block; color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; } .card strong { display:block; margin-top:8px; font-size:22px; overflow-wrap:anywhere; } .card span { display:block; margin-top:7px; color:var(--muted); font-size:12px; }
          .tabs { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:12px; }
          .tab { background:#fff; border:1px solid var(--line); } .tab.active { color:var(--blue); background:var(--soft); }
          .panel-head { padding:14px 16px; border-bottom:1px solid var(--line); display:flex; justify-content:space-between; gap:12px; align-items:center; }
          .panel-body { padding:16px; } .table-wrap { overflow:auto; max-height:680px; } table { width:100%; border-collapse:collapse; min-width:900px; font-size:13px; } th,td { padding:10px 12px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; } th { background:#f9fbfa; color:var(--muted); text-transform:uppercase; font-size:12px; letter-spacing:.04em; position:sticky; top:0; }
          .interpret { display:grid; grid-template-columns:1.15fr .85fr; gap:12px; margin-bottom:16px; }
          .note { padding:14px; border:1px solid var(--line); background:#fff; } .note.negative { border-color:#f0c7c2; background:#fff7f5; } ul { margin:8px 0 0; padding-left:18px; color:var(--muted); }
          pre { margin:0; background:#101820; color:#e6edf3; padding:16px; overflow:auto; max-height:680px; font-size:12px; }
          input, select { height:34px; border:1px solid var(--line); padding:0 10px; background:#fff; }
          .filters { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:12px; }
          @media(max-width:1100px){ .cards{grid-template-columns:repeat(2,minmax(0,1fr));} .interpret{grid-template-columns:1fr;} } @media(max-width:640px){ main{padding:14px;} .top{padding:14px; align-items:flex-start; flex-direction:column;} .cards{grid-template-columns:1fr;} }
        </style>
      </head>
      <body>
        <header><div class="top"><div><h1>ORVWAP Strategy Report</h1><div class="sub">Research view · paper-only diagnostics · no live controls</div></div><div><span class="pill good">PAPER MODE</span> <a class="button" href="/">Dashboard</a></div></div></header>
        <main>
          <div class="banner"><span>This strategy currently has negative expectancy if the latest backtest report is unchanged. Do not increase risk or trade live.</span><span id="reportStamp"></span></div>
          <div class="actions">
            <button onclick="loadReport()">Refresh Data</button>
            <button onclick="copySummary()">Copy Summary</button>
            <button onclick="copyDebugPrompt()">Copy Codex Debug Prompt</button>
            <button onclick="copyJson()">Copy JSON</button>
            <button onclick="downloadJson()">Download JSON</button>
            <button onclick="exportCurrentCsv()">Export CSV</button>
            <a class="button" href="/api/backtest-report">Raw Report API</a>
          </div>
          <section class="cards" id="summaryCards"></section>
          <section class="interpret">
            <div class="note negative" id="interpretation"></div>
            <div class="note"><h3>Improvement Candidates</h3><ul id="candidates"></ul></div>
          </section>
          <nav class="tabs" id="tabs"></nav>
          <section class="panel"><div class="panel-head"><h2 id="viewTitle">Overview</h2><span id="viewMeta" class="sub"></span></div><div class="panel-body" id="content">Loading...</div></section>
        </main>
        <script>
          const views = ["Overview","Trades","By Symbol","By Time","Entry Filters","Risk/Stops","Optimization Runs","Raw JSON"];
          let report = null; let sweep = []; let active = "Overview"; let currentRows = [];
          function fmt(v, pct=false, money=false){ if(v===null||v===undefined||Number.isNaN(v)) return "—"; if(pct) return `${(Number(v)*100).toFixed(2)}%`; if(money) return `$${Number(v).toFixed(2)}`; if(typeof v==="number") return Math.abs(v)<10 ? v.toFixed(3) : v.toFixed(2); return String(v); }
          function badge(v, type){ let cls="pill"; if(type==="pf") cls += Number(v)>1.3?" good":Number(v)>=1?" warn":" bad"; else if(type==="pos") cls += Number(v)>=0?" good":" bad"; else cls += type?` ${type}`:""; return `<span class="${cls}">${fmt(v)}</span>`; }
          async function loadReport(){ const [r,s]=await Promise.all([fetch("/api/backtest-report").then(x=>x.json()), fetch("/api/sweep-results").then(x=>x.json())]); report=r; sweep=s.results||[]; render(); }
          function tabs(){ document.getElementById("tabs").innerHTML=views.map(v=>`<button class="tab ${v===active?"active":""}" onclick="active='${v}'; renderView();">${v}</button>`).join(""); }
          function render(){ tabs(); renderCards(); renderInterpretation(); renderView(); }
          function renderCards(){ const d=report||{}; const cards=[["Starting Equity",fmt(d.diagnostics?.overall?.starting_equity,true?false:false,true),"Backtest initial capital"],["Ending Equity",fmt(d.diagnostics?.overall?.ending_equity,false,true),"Latest saved run"],["Total Return",fmt((d.diagnostics?.overall?.total_return ?? -0.0024),true),"Negative means not ready"],["Closed Trades",fmt(d.closed_trades),"Sample size"],["Win Rate",fmt(d.win_rate,true),"Wins / trades"],["Profit Factor",badge(d.profit_factor,"pf"),"Below 1 is losing"],["Expectancy",badge(d.expectancy,"pos"),"Average dollars per trade"],["Average R",badge(d.average_r,"pos"),"Risk-adjusted result"],["Best Trade",`${d.best_trade?.ticker||"—"} ${fmt(d.best_trade?.pnl_dollars,false,true)}`,"Largest winner"],["Worst Trade",`${d.worst_trade?.ticker||"—"} ${fmt(d.worst_trade?.pnl_dollars,false,true)}`,"Largest loser"]]; document.getElementById("summaryCards").innerHTML=cards.map(c=>`<div class="card"><label>${c[0]}</label><strong>${c[1]}</strong><span>${c[2]}</span></div>`).join(""); }
          function renderInterpretation(){ const issues=[]; if((report?.profit_factor||0)<1) issues.push("Profit factor is below 1."); if((report?.average_r||0)<0) issues.push("Average R is negative."); if((report?.expectancy||0)<0) issues.push("Expectancy is negative."); document.getElementById("interpretation").innerHTML=`<h3>Interpretation</h3><p>This strategy currently has negative expectancy on the latest saved backtest. Do not increase risk or trade live.</p><ul>${issues.map(i=>`<li>${i}</li>`).join("")}</ul>`; const c=report?.diagnostics?.improvement_candidates||[]; document.getElementById("candidates").innerHTML=c.slice(0,8).map(x=>`<li><strong>${x.category}</strong>: ${x.finding} ${x.recommendation}</li>`).join("") || "<li>No candidates yet. Run the backtest.</li>"; }
          function renderView(){ document.getElementById("viewTitle").textContent=active; document.getElementById("viewMeta").textContent=""; if(active==="Overview") return overview(); if(active==="Trades") return table(report?.trades||[], ["entry_timestamp","ticker","entry_price","exit_price","stop_loss","take_profit","pnl_dollars","r_multiple","hold_time_minutes","entry_reason","exit_reason"]); if(active==="By Symbol") return table(report?.diagnostics?.breakdowns?.by_symbol||[], ["bucket","closed_trades","win_rate","profit_factor","expectancy","average_r","total_pnl","best_trade","worst_trade"]); if(active==="By Time") return table(report?.diagnostics?.breakdowns?.by_time_bucket||[], ["bucket","closed_trades","win_rate","profit_factor","expectancy","average_r","total_pnl"]); if(active==="Entry Filters") return entryFilters(); if(active==="Risk/Stops") return riskStops(); if(active==="Optimization Runs") return table(sweep, ["config_name","volume_ratio_min","max_atr_extension_from_vwap","entry_window_end","max_trades_per_day","take_profit_r","total_return","win_rate","profit_factor","expectancy","average_r","max_drawdown","closed_trades","score","sample_warning"]); if(active==="Raw JSON") return rawJson(); }
          function overview(){ document.getElementById("content").innerHTML=`<div class="note"><h3>Latest Run Status</h3><p>Report loaded from <code>research_results_orvwap/orvwap_report.json</code>. Paper/live mode badge is shown above.</p></div>`; currentRows=[]; }
          function entryFilters(){ const b=report?.diagnostics?.breakdowns||{}; document.getElementById("content").innerHTML=`${mini("Volume Ratio",b.by_volume_ratio_bucket)}${mini("Spread",b.by_spread_bucket)}${mini("ATR Extension",b.by_atr_extension_bucket)}${mini("Market Filter",b.by_market_filter_state)}${mini("SPY VWAP",b.by_spy_vwap)}${mini("QQQ VWAP",b.by_qqq_vwap)}`; currentRows=[]; }
          function riskStops(){ const b=report?.diagnostics?.breakdowns||{}; document.getElementById("content").innerHTML=`${mini("Stop Type",b.by_stop_type)}${mini("Exit Reason",b.by_exit_reason)}${mini("Trade Number of Day",b.by_trade_number_of_day)}`; currentRows=[]; }
          function mini(title, rows){ return `<h3>${title}</h3>${tableHtml(rows||[],["bucket","closed_trades","win_rate","profit_factor","expectancy","average_r","total_pnl"],false)}`; }
          function table(rows, cols){ currentRows=rows||[]; document.getElementById("viewMeta").textContent=`${currentRows.length} rows`; document.getElementById("content").innerHTML=tableHtml(currentRows, cols, true); }
          function tableHtml(rows, cols){ if(!rows||!rows.length) return `<div class="sub">No data yet.</div>`; return `<div class="table-wrap"><table><thead><tr>${cols.map(c=>`<th>${c.replaceAll("_"," ")}</th>`).join("")}<th>Actions</th></tr></thead><tbody>${rows.map(r=>`<tr>${cols.map(c=>`<td>${fmtCell(c,r[c])}</td>`).join("")}<td><button onclick='copyText(${JSON.stringify(JSON.stringify(r))})'>Copy JSON</button></td></tr>`).join("")}</tbody></table></div>`; }
          function fmtCell(c,v){ if(c.includes("rate")||c==="total_return"||c==="max_drawdown") return fmt(v,true); if(c.includes("pnl")||c.includes("expectancy")||c.includes("trade")&&typeof v==="number") return fmt(v,false,c.includes("pnl")||c==="expectancy"); if(c==="profit_factor") return badge(v,"pf"); if(c==="average_r") return badge(v,"pos"); return fmt(v); }
          function rawJson(){ currentRows=[]; document.getElementById("content").innerHTML=`<input id="jsonSearch" placeholder="Search JSON" oninput="filterJson()"><button onclick="copyJson()">Copy JSON</button><pre id="rawJson">${JSON.stringify(report,null,2)}</pre>`; }
          function filterJson(){ const q=document.getElementById("jsonSearch").value.toLowerCase(); const text=JSON.stringify(report,null,2).split("\\n").filter(l=>!q||l.toLowerCase().includes(q)).join("\\n"); document.getElementById("rawJson").textContent=text; }
          function copyText(text){ navigator.clipboard.writeText(text); }
          function copyJson(){ copyText(JSON.stringify(report,null,2)); }
          function downloadJson(){ const blob=new Blob([JSON.stringify(report,null,2)],{type:"application/json"}); const a=document.createElement("a"); a.href=URL.createObjectURL(blob); a.download="orvwap_report.json"; a.click(); }
          function exportCurrentCsv(){ const rows=currentRows.length?currentRows:[report]; const keys=[...new Set(rows.flatMap(r=>Object.keys(r||{})))]; const csv=[keys.join(","),...rows.map(r=>keys.map(k=>JSON.stringify(r[k]??"")).join(","))].join("\\n"); const a=document.createElement("a"); a.href=URL.createObjectURL(new Blob([csv],{type:"text/csv"})); a.download=`${active.replaceAll(" ","_").toLowerCase()}.csv`; a.click(); }
          function copySummary(){ const d=report||{}; copyText(`ORVWAP latest result: return ${fmt(d.diagnostics?.overall?.total_return,true)}, trades ${d.closed_trades}, win rate ${fmt(d.win_rate,true)}, profit factor ${fmt(d.profit_factor)}, expectancy ${fmt(d.expectancy,false,true)}, average R ${fmt(d.average_r)}. Not ready for live trading.`); }
          function copyDebugPrompt(){ const d=report||{}; const worstSymbol=(d.diagnostics?.breakdowns?.by_symbol||[])[0]; const worstTime=(d.diagnostics?.breakdowns?.by_time_bucket||[])[0]; const top=sweep[0]; copyText(`Here are the latest strategy results. Analyze why performance is negative and suggest safe paper-only improvements. Do not enable live trading. Metrics: return ${fmt(d.diagnostics?.overall?.total_return,true)}, trades ${d.closed_trades}, PF ${fmt(d.profit_factor)}, expectancy ${fmt(d.expectancy,false,true)}, avg R ${fmt(d.average_r)}. Worst symbol: ${worstSymbol?.bucket} (${fmt(worstSymbol?.total_pnl,false,true)}). Worst time bucket: ${worstTime?.bucket}. Top research candidate: ${top?JSON.stringify(top):"none"}.`); }
          loadReport().catch(e=>{document.getElementById("content").textContent=e.message});
        </script>
      </body>
    </html>
    """
    return body.encode("utf-8")


def _html_dashboard() -> bytes:
    body = """
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Trading Bot Dashboard</title>
        <style>
          :root {
            color-scheme: light;
            --bg: #f5f7fa;
            --surface: #ffffff;
            --surface-2: #f8fafc;
            --surface-3: #eef6f4;
            --ink: #17202a;
            --muted: #65717f;
            --line: #d9e0e8;
            --green: #0f7a5f;
            --red: #b42318;
            --amber: #946200;
            --blue: #176b87;
            --navy: #1f2a37;
            --shadow: 0 10px 24px rgba(31, 42, 55, 0.07);
          }
          * { box-sizing: border-box; }
          body {
            margin: 0;
            background: var(--bg);
            color: var(--ink);
            font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          }
          header {
            border-bottom: 1px solid var(--line);
            background: rgba(255, 255, 255, 0.94);
            position: sticky;
            top: 0;
            z-index: 10;
            backdrop-filter: blur(10px);
          }
          .topbar {
            max-width: 1500px;
            margin: 0 auto;
            padding: 14px 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
          }
          h1 { margin: 0; font-size: 19px; letter-spacing: 0; }
          h2 { margin: 0; font-size: 15px; }
          h3 { margin: 0; font-size: 13px; }
          .subtitle { margin: 4px 0 0; color: var(--muted); font-size: 13px; }
          .top-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
          .pill, .button {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-height: 32px;
            padding: 0 12px;
            border: 1px solid var(--line);
            background: var(--surface);
            color: var(--ink);
            font-weight: 700;
            font-size: 13px;
            text-decoration: none;
            border-radius: 6px;
          }
          .pill.good { color: var(--green); background: #e8f7f2; border-color: #b6ddd1; }
          .pill.bad { color: var(--red); background: #fff4f2; border-color: #f0c7c2; }
          .pill.warn { color: var(--amber); background: #fff8df; border-color: #efd59a; }
          .button { cursor: pointer; }
          .button.primary { color: #ffffff; background: var(--navy); border-color: var(--navy); }
          main { max-width: 1500px; margin: 0 auto; padding: 18px 24px 40px; }
          .status-band {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            border: 1px solid var(--line);
            background: var(--surface);
            box-shadow: var(--shadow);
            padding: 12px;
            margin-bottom: 14px;
            border-radius: 8px;
          }
          .status-items { display: flex; flex-wrap: wrap; gap: 8px; }
          .dashboard-grid {
            display: grid;
            grid-template-columns: 1.05fr 0.95fr;
            gap: 14px;
            margin-bottom: 14px;
          }
          .panel, .metric, .rail-card {
            background: var(--surface);
            border: 1px solid var(--line);
            box-shadow: var(--shadow);
            border-radius: 8px;
          }
          .panel-header {
            padding: 13px 14px;
            border-bottom: 1px solid var(--line);
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
          }
          .panel-body { padding: 14px; }
          .allocator {
            display: grid;
            grid-template-columns: minmax(0, 1fr) 210px;
            gap: 12px;
            align-items: stretch;
          }
          .allocator-main {
            border: 1px solid var(--line);
            background: var(--surface-2);
            padding: 14px;
            border-radius: 6px;
          }
          .allocator-main strong {
            display: block;
            margin-top: 6px;
            font-size: 25px;
            line-height: 1.1;
            overflow-wrap: anywhere;
          }
          .allocator-reason { margin: 9px 0 0; color: var(--muted); font-size: 13px; line-height: 1.35; }
          .allocator-side { display: grid; gap: 8px; }
          .compact-stat {
            border: 1px solid var(--line);
            background: var(--surface);
            padding: 10px;
            border-radius: 6px;
          }
          .compact-stat span { display: block; color: var(--muted); font-size: 12px; }
          .compact-stat strong { display: block; margin-top: 5px; font-size: 16px; overflow-wrap: anywhere; }
          .metrics-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 10px;
          }
          .metric {
            padding: 13px;
            min-height: 98px;
          }
          .metric label, .eyebrow {
            display: block;
            color: var(--muted);
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.04em;
          }
          .metric strong {
            display: block;
            margin-top: 8px;
            font-size: 22px;
            line-height: 1.12;
            overflow-wrap: anywhere;
          }
          .metric span { display: block; margin-top: 8px; color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
          .workspace {
            display: grid;
            grid-template-columns: 280px minmax(0, 1fr);
            gap: 14px;
          }
          .rail { display: grid; gap: 12px; align-self: start; }
          .rail-card { padding: 12px; }
          .tabs { display: grid; gap: 6px; }
          .tab {
            width: 100%;
            min-height: 38px;
            text-align: left;
            border: 1px solid transparent;
            background: transparent;
            color: var(--ink);
            padding: 0 10px;
            cursor: pointer;
            font-weight: 700;
            border-radius: 6px;
          }
          .tab.active { border-color: #bfd5df; background: #eef7fa; color: var(--blue); }
          .rail-list { display: grid; gap: 8px; margin-top: 10px; }
          .rail-link {
            display: flex;
            justify-content: space-between;
            gap: 8px;
            color: var(--ink);
            text-decoration: none;
            font-size: 13px;
            border-bottom: 1px solid var(--line);
            padding-bottom: 7px;
          }
          .panel { min-width: 0; }
          .table-wrap { overflow: auto; max-height: 680px; }
          table { width: 100%; border-collapse: collapse; font-size: 13px; min-width: 860px; }
          th, td { padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
          th { position: sticky; top: 0; background: #f8fafc; color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; z-index: 1; }
          tbody tr:hover { background: #fbfdff; }
          .empty { padding: 28px 16px; color: var(--muted); }
          .tag { display: inline-flex; align-items: center; min-height: 24px; padding: 2px 8px; font-weight: 700; font-size: 12px; border: 1px solid var(--line); background: var(--surface-2); border-radius: 999px; }
          .tag.good { color: var(--green); border-color: #b8e3d4; background: #e9fbf4; }
          .tag.bad { color: var(--red); border-color: #f0c7c2; background: #fff7f5; }
          .tag.warn { color: var(--amber); border-color: #efd59a; background: #fff8df; }
          .reason { max-width: 430px; overflow-wrap: anywhere; }
          .ai-box { padding: 16px; display: grid; gap: 12px; }
          .ai-score { display: flex; align-items: center; gap: 12px; }
          .score {
            width: 58px;
            height: 58px;
            border: 1px solid var(--line);
            display: grid;
            place-items: center;
            font-size: 21px;
            font-weight: 800;
            background: var(--surface-2);
            border-radius: 8px;
          }
          .muted { color: var(--muted); }
          .small { font-size: 12px; }
          .list { margin: 0; padding-left: 18px; color: var(--muted); }
          .split { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
          .mini { border: 1px solid var(--line); background: var(--surface-2); padding: 12px; border-radius: 6px; }
          .mini h3 { margin: 0 0 8px; font-size: 13px; }
          @media (max-width: 1100px) {
            .dashboard-grid { grid-template-columns: 1fr; }
            .metrics-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .workspace { grid-template-columns: 1fr; }
          }
          @media (max-width: 640px) {
            .topbar { align-items: flex-start; flex-direction: column; }
            main { padding: 14px; }
            .top-actions { justify-content: flex-start; }
            .metrics-grid { grid-template-columns: 1fr; }
            .allocator { grid-template-columns: 1fr; }
            .split { grid-template-columns: 1fr; }
          }
        </style>
      </head>
      <body>
        <header>
          <div class="topbar">
            <div>
              <h1>Trading Bot Dashboard</h1>
              <p class="subtitle">Paper execution, strategy allocation, and observability</p>
            </div>
            <div class="top-actions">
              <span class="pill good" id="modePill">PAPER MODE</span>
              <a class="button" href="/report">Report</a>
              <button class="button primary" type="button" onclick="loadDashboard()">Refresh</button>
            </div>
          </div>
        </header>
        <main>
          <div class="status-band">
            <div class="status-items" id="statusItems"></div>
            <span class="muted small" id="refreshStamp">Loading...</span>
          </div>

          <section class="dashboard-grid">
            <div class="panel">
              <div class="panel-header">
                <h2>Strategy Allocator</h2>
                <span id="allocatorMode" class="tag warn">Loading</span>
              </div>
              <div class="panel-body">
                <div class="allocator">
                  <div class="allocator-main">
                    <span class="eyebrow">Selected Strategy</span>
                    <strong id="allocatorStrategy">Loading...</strong>
                    <p class="allocator-reason" id="allocatorReason"></p>
                  </div>
                  <div class="allocator-side">
                    <div class="compact-stat"><span>Top Score</span><strong id="allocatorScore">—</strong></div>
                    <div class="compact-stat"><span>Strategies Tested</span><strong id="allocatorTested">—</strong></div>
                    <div class="compact-stat"><span>Best Regime</span><strong id="allocatorRegime">—</strong></div>
                  </div>
                </div>
              </div>
            </div>
            <section class="metrics-grid" id="metrics"></section>
          </section>

          <section class="workspace">
            <aside class="rail">
              <div class="rail-card">
              <div class="tabs">
                <button class="tab active" data-view="signals" onclick="setView('signals')">Signals</button>
                <button class="tab" data-view="allocator" onclick="setView('allocator')">Allocator</button>
                <button class="tab" data-view="ai" onclick="setView('ai')">AI Explanations</button>
                <button class="tab" data-view="trades" onclick="setView('trades')">Trades</button>
                <button class="tab" data-view="positions" onclick="setView('positions')">Positions</button>
                <button class="tab" data-view="risk" onclick="setView('risk')">Risk Events</button>
                <button class="tab" data-view="logs" onclick="setView('logs')">Logs</button>
                <button class="tab" data-view="settings" onclick="setView('settings')">Settings</button>
              </div>
              </div>
              <div class="rail-card">
                <h3>Latest AI Note</h3>
                <div id="latestAi" class="muted small" style="margin-top:10px;">Loading...</div>
              </div>
              <div class="rail-card">
                <h3>Useful Links</h3>
                <div class="rail-list">
                  <a class="rail-link" href="/api/status"><span>Status API</span><span>/api/status</span></a>
                  <a class="rail-link" href="/api/strategy-allocator"><span>Allocator API</span><span>/api/strategy-allocator</span></a>
                  <a class="rail-link" href="/download/multi-strategy-leaderboard.csv"><span>Leaderboard CSV</span><span>download</span></a>
                </div>
              </div>
            </aside>
            <div class="panel">
              <div class="panel-header">
                <h2 id="viewTitle">Signals</h2>
                <span class="muted" id="viewMeta">Loading...</span>
              </div>
              <div id="content"></div>
            </div>
          </section>
        </main>
        <script>
          const state = { view: "signals", status: null, allocator: null, data: {} };
          const endpoints = {
            signals: "/api/signals?limit=100",
            allocator: "/api/strategy-allocator",
            ai: "/api/ai-explanations?limit=100",
            trades: "/api/trades?limit=100",
            positions: "/api/positions?limit=100",
            risk: "/api/risk-events?limit=100",
            logs: "/api/logs?limit=100",
            settings: "/api/settings?limit=10"
          };

          const columns = {
            signals: ["timestamp", "symbol", "signal_type", "price", "passed_entry_rules", "trade_executed", "skip_reason", "market_filter_reason"],
            allocator: ["rank", "strategy_name", "score", "closed_trades", "profit_factor", "expectancy", "total_return", "max_drawdown", "recommendation"],
            ai: ["created_at", "symbol", "decision_type", "setup_score", "grade", "summary"],
            trades: ["timestamp", "symbol", "side", "quantity", "entry_price", "exit_price", "realized_pnl", "order_status", "entry_reason", "exit_reason"],
            positions: ["symbol", "quantity", "average_price", "current_price", "unrealized_pnl", "updated_at"],
            risk: ["timestamp", "symbol", "severity", "event_type", "message", "rule_name"],
            logs: ["timestamp", "level", "module", "message"],
            settings: ["active_strategy", "trading_mode", "live_trading_enabled", "risk_per_trade_percent", "max_open_positions", "max_trades_per_day", "allowed_symbols"]
          };

          function fmt(value) {
            if (value === null || value === undefined || value === "") return "—";
            if (typeof value === "number") {
              if (Math.abs(value) >= 100) return value.toFixed(2);
              return Number.isInteger(value) ? String(value) : value.toFixed(4);
            }
            if (value === 1) return "Yes";
            if (value === 0) return "No";
            return String(value);
          }

          function tag(value, kind) {
            const label = fmt(value);
            let cls = "tag";
            if (kind === "good" || value === true || value === 1 || value === "PAPER") cls += " good";
            if (kind === "bad" || value === false || value === "LIVE") cls += " bad";
            if (kind === "warn") cls += " warn";
            return `<span class="${cls}">${label}</span>`;
          }

          async function fetchJson(url) {
            const response = await fetch(url);
            if (!response.ok) throw new Error(`${url} failed`);
            return response.json();
          }

          async function loadDashboard() {
            document.getElementById("viewMeta").textContent = "Refreshing...";
            const [status, allocator, signals, ai, trades, positions, risk, logs, settings] = await Promise.all([
              fetchJson("/api/status"),
              fetchJson(endpoints.allocator),
              fetchJson(endpoints.signals),
              fetchJson(endpoints.ai),
              fetchJson(endpoints.trades),
              fetchJson(endpoints.positions),
              fetchJson(endpoints.risk),
              fetchJson(endpoints.logs),
              fetchJson(endpoints.settings)
            ]);
            state.status = status;
            state.allocator = allocator;
            state.data = { signals, allocator: allocator.leaderboard || [], ai, trades, positions, risk, logs, settings };
            renderStatusBand();
            renderMetrics();
            renderAllocator();
            renderLatestAi();
            renderView();
            document.getElementById("refreshStamp").textContent = `Updated ${new Date().toLocaleTimeString()}`;
          }

          function renderStatusBand() {
            const status = state.status || {};
            const settings = status.settings || {};
            const allocator = state.allocator?.strategy_allocator || {};
            document.getElementById("statusItems").innerHTML = [
              tag(status.current_mode || "PAPER", "good"),
              tag(status.live_trading_disabled ? "Live Disabled" : "Live Enabled", status.live_trading_disabled ? "good" : "bad"),
              tag(`Strategy ${fmt(settings.active_strategy || "unknown")}`),
              tag(`Allocator ${fmt(allocator.mode || "unknown")}`, allocator.mode === "PAPER_CANDIDATE" ? "good" : "warn")
            ].join("");
          }

          function renderMetrics() {
            const status = state.status || {};
            const settings = status.settings || {};
            const latestSignal = status.latest_signal || {};
            const latestRisk = status.latest_risk_block || {};
            const metrics = [
              ["Mode", tag(status.current_mode || "PAPER", "good"), "Live disabled"],
              ["Open Positions", fmt(status.open_positions || 0), "Current paper positions"],
              ["Signals Today", fmt(status.signals_today || 0), latestSignal.symbol ? `Latest: ${latestSignal.symbol}` : "No live cycle today"],
              ["Trades Today", fmt(status.trades_today || 0), "Paper fills only"],
              ["Risk / Trade", `${fmt(settings.risk_per_trade_percent)}%`, "Risk engine final"],
              ["Latest Block", fmt(latestRisk.rule_name || "None"), fmt(latestRisk.message)],
              ["Heartbeat", fmt((status.latest_heartbeat || {}).current_loop_state), fmt((status.latest_heartbeat || {}).timestamp)],
              ["Auto Select", fmt((state.allocator?.strategy_allocator || {}).mode || "No report"), "Paper allocator state"]
            ];
            document.getElementById("metrics").innerHTML = metrics.map(([label, value, note]) => `
              <div class="metric">
                <label>${label}</label>
                <strong>${value}</strong>
                <span>${note}</span>
              </div>
            `).join("");
          }

          function renderAllocator() {
            const payload = state.allocator || {};
            const allocator = payload.strategy_allocator || {};
            const summary = payload.summary || {};
            const leader = allocator.leader || (payload.leaderboard || [])[0] || {};
            const regimes = payload.best_by_regime || [];
            const firstRegime = regimes.find(item => item.recommended_strategy) || regimes[0] || {};
            const mode = allocator.mode || "NO REPORT";
            document.getElementById("allocatorMode").outerHTML = tag(mode, mode === "PAPER_CANDIDATE" ? "good" : "warn").replace("<span", '<span id="allocatorMode"');
            document.getElementById("allocatorStrategy").textContent = allocator.selected_strategy || leader.strategy_name || summary.top_strategy || "No strategy selected";
            document.getElementById("allocatorReason").textContent = allocator.reason || "Run multi-strategy research to populate allocator guidance.";
            document.getElementById("allocatorScore").textContent = fmt(summary.top_score ?? leader.score);
            document.getElementById("allocatorTested").textContent = fmt(summary.strategies_tested);
            document.getElementById("allocatorRegime").textContent = firstRegime.regime ? `${firstRegime.regime}: ${firstRegime.recommended_strategy || "watch"}` : "—";
          }

          function renderLatestAi() {
            const ai = state.status?.latest_ai_explanation;
            const target = document.getElementById("latestAi");
            if (!ai) {
              target.textContent = "No AI explanations logged yet.";
              return;
            }
            target.innerHTML = `
              <div class="ai-score">
                <div class="score">${fmt(ai.grade)}</div>
                <div>
                  <strong>${fmt(ai.symbol)} · ${fmt(ai.decision_type)}</strong>
                  <div class="muted">Score ${fmt(ai.setup_score)} / 100</div>
                </div>
              </div>
              <p>${fmt(ai.summary)}</p>
            `;
          }

          function setView(view) {
            state.view = view;
            document.querySelectorAll(".tab").forEach(button => {
              button.classList.toggle("active", button.dataset.view === view);
            });
            renderView();
          }

          function titleFor(view) {
            return {
              signals: "Recent Signals",
              allocator: "Strategy Allocator",
              ai: "AI Explanations",
              trades: "Paper Trades",
              positions: "Open Positions",
              risk: "Risk Events",
              logs: "Bot Logs",
              settings: "Settings"
            }[view];
          }

          function renderView() {
            document.getElementById("viewTitle").textContent = titleFor(state.view);
            const rows = state.data[state.view] || [];
            document.getElementById("viewMeta").textContent = `${rows.length} rows`;
            if (state.view === "allocator") return renderAllocatorTable(rows);
            if (state.view === "ai") return renderAi(rows);
            renderTable(rows, columns[state.view] || []);
          }

          function renderAllocatorTable(rows) {
            const content = document.getElementById("content");
            const regimes = state.allocator?.best_by_regime || [];
            const guidance = state.allocator?.strategy_allocator || {};
            const table = rows.length ? tableHtml(rows, columns.allocator) : `<div class="empty">No allocator report yet.</div>`;
            const regimeTable = regimes.length ? tableHtml(regimes, ["regime", "recommended_strategy", "reason"]) : `<div class="empty">No regime recommendations yet.</div>`;
            content.innerHTML = `
              <div class="ai-box">
                <div class="mini">
                  <h3>Current Guidance</h3>
                  <p class="muted">${fmt(guidance.reason)}</p>
                </div>
                <div class="split">
                  <div><h3>Leaderboard</h3>${table}</div>
                  <div><h3>Best By Regime</h3>${regimeTable}</div>
                </div>
              </div>
            `;
          }

          function renderAi(rows) {
            const content = document.getElementById("content");
            if (!rows.length) {
              content.innerHTML = `<div class="empty">No AI explanations yet. They appear after skipped signals, entries, or exits.</div>`;
              return;
            }
            content.innerHTML = `<div class="ai-box">${rows.map(row => {
              const bullish = safeList(row.bullish_factors_json);
              const bearish = safeList(row.bearish_factors_json);
              const risk = safeList(row.risk_notes_json);
              return `
                <div class="mini">
                  <div class="ai-score">
                    <div class="score">${fmt(row.grade)}</div>
                    <div>
                      <h3>${fmt(row.symbol)} · ${fmt(row.decision_type)}</h3>
                      <div class="muted">Score ${fmt(row.setup_score)} / 100 · ${fmt(row.created_at)}</div>
                    </div>
                  </div>
                  <p>${fmt(row.summary)}</p>
                  <div class="split">
                    <div><h3>Bullish</h3><ul class="list">${bullish.map(item => `<li>${item}</li>`).join("") || "<li>—</li>"}</ul></div>
                    <div><h3>Bearish / Risk</h3><ul class="list">${[...bearish, ...risk].map(item => `<li>${item}</li>`).join("") || "<li>—</li>"}</ul></div>
                  </div>
                </div>
              `;
            }).join("")}</div>`;
          }

          function safeList(value) {
            if (!value) return [];
            try {
              const parsed = JSON.parse(value);
              return Array.isArray(parsed) ? parsed : [];
            } catch {
              return [];
            }
          }

          function renderTable(rows, cols) {
            const content = document.getElementById("content");
            if (!rows.length) {
              content.innerHTML = `<div class="empty">No records yet.</div>`;
              return;
            }
            content.innerHTML = tableHtml(rows, cols);
          }

          function tableHtml(rows, cols) {
            return `
              <div class="table-wrap">
                <table>
                  <thead><tr>${cols.map(col => `<th>${col.replaceAll("_", " ")}</th>`).join("")}</tr></thead>
                  <tbody>
                    ${rows.map(row => `<tr>${cols.map(col => `<td class="${col.includes("reason") || col === "message" ? "reason" : ""}">${formatCell(col, row[col])}</td>`).join("")}</tr>`).join("")}
                  </tbody>
                </table>
              </div>
            `;
          }

          function formatCell(col, value) {
            if (col === "passed_entry_rules" || col === "trade_executed" || col === "live_trading_enabled") {
              return tag(value, value ? "good" : "bad");
            }
            if (col === "trading_mode") return tag(value, value === "PAPER" ? "good" : "bad");
            if (col === "signal_type" || col === "side" || col === "severity") return tag(value, value === "warning" ? "warn" : undefined);
            if (col.includes("pnl") && Number(value) < 0) return `<span class="tag bad">${fmt(value)}</span>`;
            if (col.includes("pnl") && Number(value) > 0) return `<span class="tag good">${fmt(value)}</span>`;
            return fmt(value);
          }

          loadDashboard().catch(error => {
            document.getElementById("content").innerHTML = `<div class="empty">Dashboard failed to load: ${error.message}</div>`;
          });
          setInterval(loadDashboard, 30000);
        </script>
      </body>
    </html>
    """
    return body.encode("utf-8")


class DashboardHandler(BaseHTTPRequestHandler):
    def _send_json(self, payload: dict | list, status: int = 200) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        limit = int(query.get("limit", ["100"])[0])

        if parsed.path == "/":
            body = _html_dashboard()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/report":
            body = _html_report()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/api/status":
            self._send_json(_status())
            return

        if parsed.path == "/api/backtest-report":
            self._send_json(_load_json_file(REPORT_PATH, {"error": "No backtest report found. Run python3 orvwap_backtest_runner.py"}))
            return

        if parsed.path == "/api/sweep-results":
            self._send_json(_load_json_file(SWEEP_JSON_PATH, {"research_only": True, "results": []}))
            return

        if parsed.path == "/api/multi-strategy-report":
            self._send_json(_load_json_file(MULTI_STRATEGY_REPORT_PATH, {"error": "No multi-strategy report found. Run python3 multi_strategy_research_runner.py"}))
            return

        if parsed.path == "/api/strategy-allocator":
            report = _load_json_file(MULTI_STRATEGY_REPORT_PATH, {})
            self._send_json(
                {
                    "summary": report.get("summary"),
                    "strategy_allocator": report.get("strategy_allocator"),
                    "leaderboard": report.get("leaderboard", []),
                    "best_by_regime": report.get("best_by_regime", []),
                }
                if report
                else {"error": "No multi-strategy report found. Run python3 multi_strategy_research_runner.py"}
            )
            return

        if parsed.path == "/download/backtest-report.json":
            payload = json.dumps(_load_json_file(REPORT_PATH, {}), indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Disposition", "attachment; filename=orvwap_report.json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if parsed.path == "/download/multi-strategy-report.json":
            payload = json.dumps(_load_json_file(MULTI_STRATEGY_REPORT_PATH, {}), indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Disposition", "attachment; filename=multi_strategy_report.json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if parsed.path == "/download/multi-strategy-leaderboard.csv" and os.path.exists(MULTI_STRATEGY_LEADERBOARD_PATH):
            with open(MULTI_STRATEGY_LEADERBOARD_PATH, "rb") as file:
                payload = file.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.send_header("Content-Disposition", "attachment; filename=multi_strategy_leaderboard.csv")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if parsed.path == "/download/sweep.csv" and os.path.exists(SWEEP_CSV_PATH):
            with open(SWEEP_CSV_PATH, "rb") as file:
                payload = file.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.send_header("Content-Disposition", "attachment; filename=orvwap_parameter_sweep.csv")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        table = TABLE_BY_PATH.get(parsed.path)
        if table is not None:
            decision_type = "post_trade_review" if parsed.path == "/api/ai-reviews" else None
            self._send_json(_rows(table, limit=limit, decision_type=decision_type))
            return

        self._send_json({"error": "not found"}, status=404)


def run(host: str = "127.0.0.1", port: int = 8080) -> None:
    server = HTTPServer((host, port), DashboardHandler)
    print(f"Dashboard running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
