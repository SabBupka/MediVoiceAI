param([string]$BaseUrl = "http://127.0.0.1:8000")

$ErrorActionPreference = "Stop"
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$BaseUrl = $BaseUrl.TrimEnd("/")

function Invoke-DemoApi([string]$Method, [string]$Path, $Data = $null) {
    $uri = "$BaseUrl$Path"
    Write-Host "`n$Method $uri" -ForegroundColor DarkCyan
    if ($null -eq $Data) {
        return Invoke-RestMethod -Method $Method -Uri $uri -TimeoutSec 60
    }
    $json = ConvertTo-Json -InputObject $Data -Depth 10 -Compress
    Write-Host $json -ForegroundColor DarkGray
    $body = [Text.Encoding]::UTF8.GetBytes($json)
    return Invoke-RestMethod -Method $Method -Uri $uri `
        -ContentType "application/json; charset=utf-8" -Body $body -TimeoutSec 60
}

function Send-Turn([string]$SessionId, [string]$Text) {
    Write-Host "`nПациент: $Text" -ForegroundColor Yellow
    $reply = Invoke-DemoApi "POST" "/api/sessions/$SessionId/message" @{ text = $Text }
    Write-Host "Ассистент: $($reply.response)" -ForegroundColor Green
    return $reply
}

Write-Host "`nДЕМО · ЗАПИСЬ К ТЕРАПЕВТУ" -ForegroundColor Green

$health = Invoke-DemoApi "GET" "/health"
if ($health.status -ne "ok") { throw "API недоступно." }
if ($health.registry_mode -ne "mock") {
    throw "Демо остановлено: разрешён только локальный mock-реестр."
}
Write-Host "Реестр: $($health.registry_mode) · LLM: $($health.llm) · ASR/TTS: $($health.asr)/$($health.tts)"

$utterance = "Мне нужно попасть к врачу на плановый осмотр"
Write-Host "`nПациент: $utterance" -ForegroundColor Yellow
$classification = Invoke-DemoApi "POST" "/api/voice/process-text" @{ text = $utterance }
Write-Host "Намерение: $($classification.intent) · источник: $($classification.source)"
Write-Host "Ответ: $($classification.text)" -ForegroundColor Green

$specialty = [uri]::EscapeDataString("терапевт")
$doctors = Invoke-DemoApi "GET" "/api/doctors?specialty=$specialty"
$slots = Invoke-DemoApi "GET" "/api/slots?specialty=$specialty&limit=50"
if (-not $slots -or -not $doctors) {
    throw "Нет врачей или свободных слотов терапевта. Проверьте импорт расписания."
}
$slot = $slots | Select-Object -First 1
$doctor = $doctors | Where-Object { $_.full_name -eq $slot.doctor_name } | Select-Object -First 1
if (-not $doctor) { throw "Врач из расписания отсутствует в справочнике API." }
Write-Host "`nРасписание: $($slot.doctor_name) · $($slot.scheduled_at)" -ForegroundColor Cyan

$session = Invoke-DemoApi "POST" "/api/sessions/incoming" @{ caller_id = "checkpoint-demo" }
Write-Host "Сессия: $($session.id) · $($session.status)"

Send-Turn $session.id "Хочу записаться к терапевту" | Out-Null
Send-Turn $session.id "Демо Тест 12 сентября 1980 года" | Out-Null
$identityReply = Send-Turn $session.id "Да"
$dateText = $slot.scheduled_at.Substring(0, 10)
$dateReply = $identityReply
if ($identityReply.response -notmatch "На какую дату") {
    $dateReply = Send-Turn $session.id $doctor.full_name
}
$dateReply = Send-Turn $session.id $dateText
if ($dateReply.response -match "К кому записать|К кому именно") {
    $dateReply = Send-Turn $session.id $doctor.full_name
}
$timeReply = Send-Turn $session.id $slot.scheduled_at.Substring(11, 5)
if ($timeReply.response -match "Записать вас") {
    Send-Turn $session.id "Да" | Out-Null
} else {
    throw "Сценарий не дошёл до подтверждения записи: $($timeReply.response)"
}

$clients = Invoke-DemoApi "GET" "/api/clients?last_name=%D0%94%D0%B5%D0%BC%D0%BE&first_name=%D0%A2%D0%B5%D1%81%D1%82&birth_date=12.09.1980"
$client = $clients | Select-Object -First 1
if ($client) {
    $visits = Invoke-DemoApi "GET" "/api/visits?client_id=$($client.id)"
    $visits | Select-Object id,status,scheduled_at,doctor | ConvertTo-Json -Depth 5
}

Write-Host "`nГотово · сессия $($session.id)" -ForegroundColor Green
