# iran/xray — Placeholder for the Xray binary

Place the **Linux x86_64 Xray binary** in this directory as `xray` before
building `iran.zip`.

## How to download (do this ONCE on a machine with internet access)

```bash
# Download the latest release
curl -L https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip \
     -o Xray-linux-64.zip

# Extract only the xray binary
unzip -j Xray-linux-64.zip xray -d .

# Make it executable
chmod +x xray
```

The file must be placed at:

```
iran/xray/xray
```

If the binary is missing when `install.sh` runs in `xray_vless` mode,
the installer will exit with a clear error message.
