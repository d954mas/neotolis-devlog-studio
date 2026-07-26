param(
    [string]$ChannelUrl = "https://www.youtube.com/@zerahgames/videos",
    [string]$OutputDirectory = "data/research/zerah_games/source",
    [string]$PythonCommand = "py",
    [string]$PythonVersion = "-3.12"
)

$ErrorActionPreference = "Stop"
$destination = [System.IO.Path]::GetFullPath(
    (Join-Path (Get-Location) $OutputDirectory)
)
New-Item -ItemType Directory -Force -Path $destination | Out-Null

$outputTemplate = Join-Path $destination (
    "%(upload_date)s_%(id)s_%(title).80B.%(ext)s"
)

& $PythonCommand $PythonVersion -m yt_dlp `
    --ignore-errors `
    --no-overwrites `
    --continue `
    --format "bestvideo[height<=1080]+bestaudio/best[height<=1080]" `
    --merge-output-format mp4 `
    --write-info-json `
    --write-description `
    --write-thumbnail `
    --write-auto-subs `
    --write-subs `
    --sub-langs "en.*,en" `
    --convert-subs srt `
    --embed-metadata `
    --output $outputTemplate `
    $ChannelUrl

if ($LASTEXITCODE -ne 0) {
    throw "yt-dlp failed with exit code $LASTEXITCODE"
}

Write-Output "Synced channel evidence to $destination"
