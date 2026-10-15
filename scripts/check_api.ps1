$ErrorActionPreference = "Stop"
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$base = "http://127.0.0.1:8000"

function Check($name, $script) {
    try {
        & $script | Out-Null
        Write-Host "[OK] $name" -ForegroundColor Green
    } catch {
        Write-Host "[FAIL] $name :: $($_.Exception.Message)" -ForegroundColor Red
        throw
    }
}

Check "health" { Invoke-RestMethod "$base/health" }
Check "doctors" { Invoke-RestMethod "$base/api/doctors" }
Check "slots" { Invoke-RestMethod "$base/api/slots?limit=3" }
Check "knowledge" {
    Invoke-RestMethod "$base/api/knowledge/answer?question=режим%20работы"
}
Check "voice text pipeline" {
    $voiceBody = [Text.Encoding]::UTF8.GetBytes(
        (@{text="Хочу записаться к терапевту"} | ConvertTo-Json)
    )
    Invoke-RestMethod -Method Post -Uri "$base/api/voice/process-text" `
        -ContentType "application/json; charset=utf-8" -Body $voiceBody
}

$clientBody = [Text.Encoding]::UTF8.GetBytes(
    (@{last_name="ApiCheck"; first_name="Local"; birth_date="12.09.1980"} | ConvertTo-Json)
)
$client = Invoke-RestMethod -Method Post -Uri "$base/api/clients" `
    -ContentType "application/json; charset=utf-8" `
    -Body $clientBody
Check "create client" { $client }
Check "list clients" {
    Invoke-RestMethod "$base/api/clients?last_name=ApiCheck&first_name=Local&birth_date=12.09.1980"
}
Check "get client" { Invoke-RestMethod "$base/api/clients/$($client.id)" }
Check "patch client" {
    Invoke-RestMethod -Method Patch -Uri "$base/api/clients/$($client.id)" `
        -ContentType "application/json" -Body '{"comment":"API-check"}'
}

$slots = Invoke-RestMethod "$base/api/slots?limit=3"
$doctors = Invoke-RestMethod "$base/api/doctors"
$slot = $slots[0]
$doctor = @($doctors | Where-Object { $_.full_name -eq $slot.doctor_name } | Select-Object -First 1)[0]
$visit = Invoke-RestMethod -Method Post -Uri "$base/api/visits" `
    -ContentType "application/json; charset=utf-8" `
    -Body (@{
        client_id = [int]$client.id
        doctor_id = [int]$doctor.id
        scheduled_at = $slot.scheduled_at
    } | ConvertTo-Json)
Check "create visit" { $visit }
Check "list visits" { Invoke-RestMethod "$base/api/visits?client_id=$($client.id)" }
Check "get visit" { Invoke-RestMethod "$base/api/visits/$($visit.id)" }

$otherScheduledAt = $null
foreach ($candidate in @(Invoke-RestMethod "$base/api/slots?limit=50")) {
    if ($candidate.PSObject.Properties.Name -contains "scheduled_at" `
        -and $candidate.doctor_id -eq $slot.doctor_id `
        -and $candidate.scheduled_at -ne $slot.scheduled_at) {
        $otherScheduledAt = [string]$candidate.scheduled_at
        break
    }
}
if ($otherScheduledAt) {
    Check "reschedule visit" {
        Invoke-RestMethod -Method Patch -Uri "$base/api/visits/$($visit.id)" `
            -ContentType "application/json; charset=utf-8" `
            -Body (@{ scheduled_at = [string]$otherScheduledAt } | ConvertTo-Json)
    }
}
Check "create escalation" {
    Invoke-RestMethod -Method Post -Uri "$base/api/escalations?client_id=$($client.id)&description=API-check"
}
Check "list escalations" { Invoke-RestMethod "$base/api/escalations" }

$reminder = Invoke-RestMethod -Method Post -Uri "$base/api/reminders" `
    -ContentType "application/json" `
    -Body (@{visit_id = [int]$visit.id; caller_id = "api-check"} | ConvertTo-Json)
Check "create reminder" { $reminder }
Check "get reminder" { Invoke-RestMethod "$base/api/reminders/$($reminder.id)" }
Check "reminder result" {
    Invoke-RestMethod -Method Post -Uri "$base/api/reminders/$($reminder.id)/result" `
        -ContentType "application/json" -Body '{"result":"no_answer"}'
}
Check "feedback" {
    Invoke-RestMethod -Method Post -Uri "$base/api/feedback" `
        -ContentType "application/json" -Body '{"score":5,"comment":"API-check"}'
}
Check "cancel visit" {
    Invoke-RestMethod -Method Patch -Uri "$base/api/visits/$($visit.id)" `
        -ContentType "application/json; charset=utf-8" `
        -Body '{"status":"Отменена"}'
}

$session = Invoke-RestMethod -Method Post -Uri "$base/api/sessions/incoming" `
    -ContentType "application/json" -Body '{"caller_id":"api-check"}'
Check "incoming session" { $session }
Check "get session" { Invoke-RestMethod "$base/api/sessions/$($session.id)" }
Check "manual escalation" {
    Invoke-RestMethod -Method Post -Uri "$base/api/sessions/$($session.id)/escalate" `
        -ContentType "application/json; charset=utf-8" `
        -Body '{"reason":"Проверка ручной эскалации"}'
}
$emergencySession = Invoke-RestMethod -Method Post -Uri "$base/api/sessions/incoming" `
    -ContentType "application/json" -Body '{"caller_id":"api-emergency-check"}'
Check "emergency escalation" {
    Invoke-RestMethod -Method Post -Uri "$base/api/sessions/$($emergencySession.id)/message" `
        -ContentType "application/json; charset=utf-8" `
        -Body '{"text":"Мне сильно давит в груди"}'
}

Write-Host "API smoke check completed." -ForegroundColor Cyan
