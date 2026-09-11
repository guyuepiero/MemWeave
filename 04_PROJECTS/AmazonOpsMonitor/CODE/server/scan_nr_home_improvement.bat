@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 新品榜可用性扫描 - Tools ^& Home Improvement
echo ============================================================
echo  类目: Tools ^& Home Improvement  (home-improvement)
echo  范围: 本大类全部叶子节点（约 1580 个待判定）
echo  时长: 约 55 分钟（sleep 1.2 秒/节点）
echo ------------------------------------------------------------
echo  1) 可随时按 Ctrl+C 或直接关窗口停止；
echo     已判定的节点结果已落缓存，不会白跑。
echo  2) 重跑本脚本会自动跳过已判定节点，接着上次继续。
echo  3) 扫描期间工作台可正常使用；若要边扫边采集，
echo     请把下面的 --sleep 1.2 改成 --sleep 2（时长约 78 分钟）。
echo ------------------------------------------------------------
echo  扫描结果查看: python -m app.nr list
echo ============================================================
echo.
".venv\Scripts\python.exe" -m app.nr scan home-improvement --sleep 1.2
echo.
echo 扫描结束。按任意键关闭窗口。
pause >nul
