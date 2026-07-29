@echo off
setlocal
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8032 .*LISTENING"') do taskkill /PID %%P /F >nul 2>&1
powershell.exe -NoProfile -Command "Start-Sleep -Seconds 2"
start "StoryMaker_C_8032" /min "F:\StoryMaker_C\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8032
powershell.exe -NoProfile -Command "$ok=$false; 1..20 | %% { Start-Sleep -Milliseconds 500; try { if((Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8032/docs' -TimeoutSec 2).StatusCode -eq 200){$ok=$true; break} } catch {} }; if($ok){Write-Output 'StoryMaker_C 8032 restart PASS'}else{Write-Error 'StoryMaker_C 8032 restart FAIL'; exit 1}"
endlocal

