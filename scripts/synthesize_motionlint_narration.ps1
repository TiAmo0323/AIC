param([Parameter(Mandatory=$true)][string]$NarrationJson)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Speech
$items=Get-Content -LiteralPath $NarrationJson -Raw -Encoding utf8 | ConvertFrom-Json
$narrator=New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $narrator.SelectVoice('Microsoft Huihui Desktop')
    $narrator.Rate=1
    foreach($item in $items) {
        $narrator.SetOutputToWaveFile($item.path)
        $narrator.Speak($item.text)
        $narrator.SetOutputToNull()
    }
} finally { $narrator.Dispose() }
