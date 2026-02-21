<#
.SYNOPSIS
    OS-Agent Environment Setup Script (Windows)
.DESCRIPTION
    Installs required LSP dependencies for OS-Agent analysis.
#>

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "  OS-Agent Environment Setup (Windows)       " -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan

# 1. Check Python
if (-not (Get-Command "python" -ErrorAction SilentlyContinue)) {
    Write-Host "[!] Python not found. Please install Python 3.10+." -ForegroundColor Red
    exit 1
}

Write-Host "[*] Checking Python dependencies..." -ForegroundColor Yellow
python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] Failed to install python dependencies." -ForegroundColor Red
}

# 2. Check Rust & rust-analyzer
Write-Host "[*] Checking Rust toolchain..." -ForegroundColor Yellow
if (-not (Get-Command "rustup" -ErrorAction SilentlyContinue)) {
    Write-Host "[+] rustup not found. Downloading rustup-init..." -ForegroundColor Green
    Invoke-WebRequest -Uri "https://win.rustup.rs" -OutFile "rustup-init.exe"
    Write-Host "[+] Running rustup-init (Silent)..." -ForegroundColor Green
    .\rustup-init.exe -y --default-toolchain stable
    Remove-Item "rustup-init.exe"
    
    # Reload Path for current session (approximate)
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
} else {
    Write-Host "[-] rustup already installed." -ForegroundColor DarkGray
}

Write-Host "[+] Setting default Rust toolchain to stable..." -ForegroundColor Green
rustup default stable
Write-Host "[+] Installing rust-analyzer..." -ForegroundColor Green
rustup component add rust-analyzer

# 3. Check clangd (C/C++)
Write-Host "[*] Checking clangd..." -ForegroundColor Yellow
if (-not (Get-Command "clangd" -ErrorAction SilentlyContinue)) {
    Write-Host "[+] Attempting to install clangd via Winget..." -ForegroundColor Green
    if (Get-Command "winget" -ErrorAction SilentlyContinue) {
        winget install LLVM.LLVM --silent
    } else {
        Write-Host "[!] Winget not found. Please install LLVM/clangd manually." -ForegroundColor Red
    }
} else {
    Write-Host "[-] clangd already installed." -ForegroundColor DarkGray
}

# 4. Check Go & gopls
Write-Host "[*] Checking gopls..." -ForegroundColor Yellow
if (-not (Get-Command "gopls" -ErrorAction SilentlyContinue)) {
    Write-Host "[+] Attempting to install gopls..." -ForegroundColor Green
    if (Get-Command "go" -ErrorAction SilentlyContinue) {
        go install golang.org/x/tools/gopls@latest
    } else {
        Write-Host "[!] Go not found. Skipping gopls installation." -ForegroundColor Yellow
    }
} else {
    Write-Host "[-] gopls already installed." -ForegroundColor DarkGray
}

# 5. Check zls
Write-Host "[*] Checking zls (Zig Language Server)..." -ForegroundColor Yellow
if (-not (Get-Command "zls" -ErrorAction SilentlyContinue)) {
    Write-Host "[!] zls not found. If analyzing Zig projects, install from https://github.com/zigtools/zls" -ForegroundColor Yellow
} else {
    Write-Host "[-] zls already installed." -ForegroundColor DarkGray
}

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host " Setup complete! If this was your first time installing Rust or LLVM, please restart your terminal." -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Cyan
