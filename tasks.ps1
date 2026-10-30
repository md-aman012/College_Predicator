<#
.SYNOPSIS
    Task runner for the JoSAA Predictor project.

.DESCRIPTION
    Runs common development tasks via Windows PowerShell.

    Usage:
        .\tasks.ps1 -Task <task>

    Tasks:
        scrape   - Run the JoSAA rank scraper
        validate - Validate raw scraped data
        clean    - Clean / normalize scraped data
        train    - Train the rank predictor model
        serve    - Start the FastAPI development server
        test     - Run the pytest test suite
#>

[CmdletBinding()]
param(
    [ValidateSet("scrape", "validate", "clean", "train", "serve", "test")]
    [string]$Task = "scrape"
)

$ErrorActionPreference = "Stop"

function Invoke-Scrape {
    Write-Host "==> Starting scrape..."
    python -m scraper.scrape
}

function Invoke-Validate {
    Write-Host "==> Validating raw data..."
    python -m pipeline.validate
}

function Invoke-Clean {
    Write-Host "==> Cleaning data..."
    python -m pipeline.clean
}

function Invoke-Train {
    Write-Host "==> Training model..."
    python -m predictor.train
}

function Invoke-Serve {
    Write-Host "==> Starting API server..."
    uvicorn api.main:app --reload
}

function Invoke-Test {
    Write-Host "==> Running tests..."
    pytest tests/ -v
}

switch ($Task) {
    "scrape"   { Invoke-Scrape }
    "validate" { Invoke-Validate }
    "clean"    { Invoke-Clean }
    "train"    { Invoke-Train }
    "serve"    { Invoke-Serve }
    "test"     { Invoke-Test }
}