$ErrorActionPreference = "Stop"
$base = "http://127.0.0.1:8031"
$email = "e2e_test_$(Get-Random)@example.com"
$pass1 = "FirstPass123"
$pass2 = "SecondPass456"
$results = @()

function Check($name, $cond, $detail) {
    $mark = if ($cond) { "PASS" } else { "FAIL" }
    Write-Output "[$mark] $name $detail"
    $script:results += [PSCustomObject]@{Name=$name; Pass=$cond; Detail=$detail}
}

# 1. register
$sess = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$r1 = Invoke-WebRequest -UseBasicParsing -WebSession $sess -Uri "$base/auth/register" -Method POST -Body @{email=$email; password=$pass1; display_name="E2E Test"}
Check "register_reaches_verify_page" ($r1.BaseResponse.ResponseUri -match "verify-email") "url=$($r1.BaseResponse.ResponseUri)"

if ($r1.Content -match 'href="(/auth/verify\?token=[A-Za-z0-9_\-]+)"') {
    $devLink = $matches[1]
    Check "dev_verification_link_found" $true $devLink
} else {
    Check "dev_verification_link_found" $false ""
    $devLink = $null
}

# 2. login blocked before verify
try {
    $r2 = Invoke-WebRequest -UseBasicParsing -WebSession $sess -Uri "$base/auth/login" -Method POST -Body @{email=$email; password=$pass1} -MaximumRedirection 0
    $loc2 = $r2.Headers.Location
} catch {
    $loc2 = $_.Exception.Response.Headers.Location
}
Check "login_blocked_before_verify" ($loc2 -match "error=") "location=$loc2"

# 3. verify email
if ($devLink) {
    try {
        $r3 = Invoke-WebRequest -UseBasicParsing -WebSession $sess -Uri "$base$devLink" -MaximumRedirection 0
        $loc3 = $r3.Headers.Location
    } catch {
        $loc3 = $_.Exception.Response.Headers.Location
    }
    Check "verify_email_redirects_to_login_verified" ($loc3 -match "verified=1") "location=$loc3"
}

# 4. login success
try {
    $r4 = Invoke-WebRequest -UseBasicParsing -WebSession $sess -Uri "$base/auth/login" -Method POST -Body @{email=$email; password=$pass1} -MaximumRedirection 0
    $loc4 = $r4.Headers.Location
} catch {
    $loc4 = $_.Exception.Response.Headers.Location
}
$hasCookie = $sess.Cookies.GetCookies($base) | Where-Object { $_.Name -eq "sc_session" }
Check "login_success_sets_cookie" ([bool]$hasCookie) "location=$loc4"

# 5. dashboard access
$r5 = Invoke-WebRequest -UseBasicParsing -WebSession $sess -Uri "$base/dashboard"
Check "dashboard_access_after_login" ($r5.StatusCode -eq 200 -and $r5.Content -match [regex]::Escape($email)) "status=$($r5.StatusCode)"

# 6. non-admin blocked from admin page
try {
    $r6 = Invoke-WebRequest -UseBasicParsing -WebSession $sess -Uri "$base/admin/members" -MaximumRedirection 0
    $code6 = $r6.StatusCode.value__
    $loc6 = $r6.Headers.Location
} catch {
    $code6 = $_.Exception.Response.StatusCode.value__
    $loc6 = $_.Exception.Response.Headers.Location
}
Check "non_admin_blocked_from_admin_page" ($loc6 -match "dashboard") "status=$code6 location=$loc6"

# 7. logout
try {
    $r7 = Invoke-WebRequest -UseBasicParsing -WebSession $sess -Uri "$base/auth/logout" -Method POST -MaximumRedirection 0
    $loc7 = $r7.Headers.Location
} catch {
    $loc7 = $_.Exception.Response.Headers.Location
}
Check "logout_redirects_to_login" ($loc7 -match "logged_out=1") "location=$loc7"

# 8. dashboard blocked after logout
try {
    $r8 = Invoke-WebRequest -UseBasicParsing -WebSession $sess -Uri "$base/dashboard" -MaximumRedirection 0
    $loc8 = $r8.Headers.Location
} catch {
    $loc8 = $_.Exception.Response.Headers.Location
}
Check "dashboard_blocked_after_logout" ($loc8 -match "login") "location=$loc8"

# 9. forgot password
$sess2 = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$r9 = Invoke-WebRequest -UseBasicParsing -WebSession $sess2 -Uri "$base/auth/forgot-password" -Method POST -Body @{email=$email}
if ($r9.Content -match 'href="(/auth/reset-password\?token=[A-Za-z0-9_\-]+)"') {
    $resetLink = $matches[1]
    Check "dev_reset_link_found" $true $resetLink
} else {
    Check "dev_reset_link_found" $false ""
    $resetLink = $null
}

if ($resetLink -and $resetLink -match "token=([A-Za-z0-9_\-]+)") {
    $resetToken = $matches[1]
    try {
        $r10 = Invoke-WebRequest -UseBasicParsing -WebSession $sess2 -Uri "$base/auth/reset-password" -Method POST -Body @{token=$resetToken; new_password=$pass2} -MaximumRedirection 0
        $loc10 = $r10.Headers.Location
    } catch {
        $loc10 = $_.Exception.Response.Headers.Location
    }
    Check "password_reset_redirects_to_login_reset" ($loc10 -match "reset=1") "location=$loc10"
}

# 10. old password fails, new password works
$sess3 = New-Object Microsoft.PowerShell.Commands.WebRequestSession
try {
    $r11 = Invoke-WebRequest -UseBasicParsing -WebSession $sess3 -Uri "$base/auth/login" -Method POST -Body @{email=$email; password=$pass1} -MaximumRedirection 0
    $loc11 = $r11.Headers.Location
} catch {
    $loc11 = $_.Exception.Response.Headers.Location
}
Check "old_password_fails_after_reset" ($loc11 -match "error=") "location=$loc11"

$sess4 = New-Object Microsoft.PowerShell.Commands.WebRequestSession
try {
    $r12 = Invoke-WebRequest -UseBasicParsing -WebSession $sess4 -Uri "$base/auth/login" -Method POST -Body @{email=$email; password=$pass2} -MaximumRedirection 0
} catch {}
$hasCookie2 = $sess4.Cookies.GetCookies($base) | Where-Object { $_.Name -eq "sc_session" }
Check "new_password_login_succeeds" ([bool]$hasCookie2) ""

$total = $results.Count
$passed = ($results | Where-Object {$_.Pass}).Count
Write-Output ""
Write-Output "=== SUMMARY: $passed/$total PASS ==="
if ($passed -lt $total) {
    $results | Where-Object {-not $_.Pass} | ForEach-Object { Write-Output "  FAIL: $($_.Name) $($_.Detail)" }
    exit 1
}
exit 0
