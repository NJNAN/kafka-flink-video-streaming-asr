$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$projectRoot = Split-Path $PSScriptRoot -Parent
$fixtureDir = Join-Path $projectRoot 'data/reliability_lab/fixtures'
New-Item -ItemType Directory -Force -Path $fixtureDir | Out-Null
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SelectVoice('Microsoft Huihui Desktop')
$synth.Rate = 0
try {
  $samples = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'fixtures.json') -Raw -Encoding UTF8 | ConvertFrom-Json
  foreach ($sample in $samples) {
    $target = Join-Path $fixtureDir ($sample.id + '.wav')
    $synth.SetOutputToWaveFile($target)
    $synth.Speak($sample.reference)
    $synth.SetOutputToNull()
  }
} finally { $synth.Dispose() }
