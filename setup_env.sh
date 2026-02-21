#!/usr/bin/env bash
# OS-Agent Environment Setup Script (Linux/Mac)
set -e

echo "============================================="
echo "  OS-Agent Environment Setup (Linux/Mac)     "
echo "============================================="

# 1. Check Python
if ! command -v python3 &> /dev/null; then
    echo "[!] Python 3 not found. Please install Python 3.10+."
    exit 1
fi

echo "[*] Checking Python dependencies..."
python3 -m pip install -r requirements.txt || echo "[!] Failed to install python dependencies. You might need to use a virtual environment or conda."

# 2. Check Rust & rust-analyzer
echo "[*] Checking Rust toolchain..."
if ! command -v rustup &> /dev/null; then
    echo "[+] Installing rustup..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    source "$HOME/.cargo/env"
else
    echo "[-] rustup already installed."
fi

echo "[+] Setting default Rust toolchain to stable..."
rustup default stable
echo "[+] Installing rust-analyzer..."
rustup component add rust-analyzer

# 3. Check clangd (C/C++)
echo "[*] Checking clangd..."
if ! command -v clangd &> /dev/null; then
    echo "[+] Attempting to install clangd..."
    if command -v apt-get &> /dev/null; then
        sudo apt-get update && sudo apt-get install -y clangd
    elif command -v brew &> /dev/null; then
        brew install llvm
    elif command -v pacman &> /dev/null; then
        sudo pacman -S --noconfirm clang
    else
        echo "[!] Unsupported package manager. Please install clangd manually."
    fi
else
    echo "[-] clangd already installed."
fi

# 4. Check Go & gopls
echo "[*] Checking gopls..."
if ! command -v gopls &> /dev/null; then
    echo "[+] Attempting to install gopls..."
    if command -v go &> /dev/null; then
        go install golang.org/x/tools/gopls@latest
    else
        echo "[!] Go not found. Skipping gopls installation."
    fi
else
    echo "[-] gopls already installed."
fi

# 5. Check Zig & zls
echo "[*] Checking zls (Zig Language Server)..."
if ! command -v zls &> /dev/null; then
    echo "[!] zls not found. If you analyze Zig projects, please install it from https://github.com/zigtools/zls"
else
    echo "[-] zls already installed."
fi

echo "============================================="
echo " Setup complete! You are ready to run OS-Agent."
echo "============================================="
