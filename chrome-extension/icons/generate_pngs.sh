#!/bin/bash
# Generate PNG icons from SVG using macOS's built-in tools

# Create temporary HTML file
cat > temp_icon.html << EOF
<!DOCTYPE html>
<html>
<head>
    <style>
        body { margin: 0; padding: 0; }
        .icon { background: #2563eb; border-radius: 12.5%; display: flex; align-items: center; justify-content: center; }
        .icon text { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; font-weight: bold; color: white; }
        .icon16 { width: 16px; height: 16px; } .icon16 text { font-size: 8px; }
        .icon48 { width: 48px; height: 48px; } .icon48 text { font-size: 20px; }
        .icon128 { width: 128px; height: 128px; } .icon128 text { font-size: 48px; }
    </style>
</head>
<body>
    <div class="icon icon16"><text>RA</text></div>
    <div class="icon icon48"><text>RA</text></div>
    <div class="icon icon128"><text>RA</text></div>
</body>
</html>
EOF

echo "Please manually create PNG icons or use an online SVG to PNG converter"
echo "Recommended: https://cloudconvert.com/svg-to-png"
echo ""
echo "For now, creating placeholder text files as icons..."

# Create placeholder files
echo "RA icon 16x16" > icon16.png
echo "RA icon 48x48" > icon48.png
echo "RA icon 128x128" > icon128.png

rm temp_icon.html

echo "Placeholder icon files created. Replace with actual PNG images before using the extension."