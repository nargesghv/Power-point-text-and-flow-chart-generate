#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, './src')

from graphdeck.research import research_topic

print("🔎 Testing research for ART topic...")
try:
    # Test research with minimal sources and no images
    bundle = research_topic("ART", max_sources=3, max_images=0)
    print(f"✅ Research completed!")
    print(f"Found {len(bundle['sources'])} sources")
    print(f"Found {len(bundle['images'])} images")
    
    # Save to file
    import json
    with open("out/research_art_test.json", "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False, indent=2)
    print("✅ Saved to out/research_art_test.json")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
