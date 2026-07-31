# Windows App Pre-Flight Checklist

## ✅ All Checks Passed

### 1. Data Files
- ✅ `ui/data/market-insights.js` - Contains `window.MARKET_INSIGHTS`
- ✅ `ui/data/bayut-pricing-history.js` - Contains `window.BAYUT_HISTORY`
- ✅ Files are properly bundled via `packaging/dxb_app.spec`

### 2. UI Pages
- ✅ `index-standalone.html` - Main page, uses bundled data (no API dependency)
- ✅ `ai-assistant.html` - Uses PROXY at `http://127.0.0.1:8787` (AI proxy server)
- ✅ `pricing-history.html` - Uses bundled `BAYUT_HISTORY` data
- ✅ `settings.html` - Uses PROXY for AI settings, handles offline gracefully

### 3. Server Configuration
- ✅ `packaging/app.py` - Serves `index-standalone.html` as default
- ✅ `tools/ai_proxy.py` - Serves `index-standalone.html` for `/` requests
- ✅ AI proxy runs on port 8787 (configurable via AI_PORT env var)

### 4. App Icon
- ✅ `icon.png` - 300x300 PNG, committed to repo
- ✅ Workflow converts to `packaging/app.ico` (multi-size: 16, 32, 48, 64, 128, 256)
- ✅ PyInstaller embeds icon in exe
- ✅ Inno Setup uses icon for installer

### 5. Error Handling
- ✅ `index-standalone.html` - Shows "Online" status, handles missing data
- ✅ `ai-assistant.html` - Handles proxy offline, shows error messages
- ✅ `settings.html` - Disables save/test buttons when proxy offline
- ✅ `pricing-history.html` - Handles missing data gracefully

### 6. Map Features
- ✅ Leaflet map loads from CDN (needs internet)
- ✅ ~40 Dubai/UAE area coordinates defined
- ✅ Colored markers by yield: green (>6%), yellow (4-6%), red (<4%)
- ✅ Click markers for area details popup

### 7. Navigation
- ✅ All internal links use relative paths
- ✅ No hardcoded `localhost:8000` in standalone pages
- ✅ Back buttons work correctly

### 8. Build Process
- ✅ GitHub Actions workflow builds on Windows
- ✅ PyInstaller creates onefile exe
- ✅ Inno Setup creates installer
- ✅ Only installer is uploaded (no portable exe)

## Known Limitations

1. **SmartScreen Warning** - App is not code-signed (no free option for private apps)
   - Users must click "More info" → "Run anyway"
   - Cheapest signing: Azure Trusted Signing ($9.99/mo)

2. **Internet Required** for:
   - Map tiles (Leaflet/CARTO)
   - Chart.js library
   - AI assistant (calls DeepSeek API)

3. **Port 8787** - Must be available (no fallback if occupied)

## Testing on Fresh Windows Install

1. Download `DubaiEstate-Setup-1.0.0.exe`
2. Run installer (bypass SmartScreen)
3. Launch app
4. Verify:
   - Window opens with custom icon
   - Shows "Online" with green bullet
   - Map displays with colored markers
   - Rankings table shows data
   - Growth tab shows areas with history
   - Pricing History page works
   - AI Assistant works (if API key configured)
   - Settings page works (if proxy running)
