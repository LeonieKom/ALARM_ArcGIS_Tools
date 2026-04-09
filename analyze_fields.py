import arcpy
from pathlib import Path

# Find example shapefiles
base_dir = Path(r"L:\ALARM\Results\Vest_Finnmark\merged\D")

tracks_file = list(base_dir.glob("tracks_*.shp"))[0] if list(base_dir.glob("tracks_*.shp")) else None
pra_file = list(base_dir.glob("pra_*.shp"))[0] if list(base_dir.glob("pra_*.shp")) else None
risk_file = list(base_dir.glob("*risk*.shp"))[0] if list(base_dir.glob("*risk*.shp")) else None

print("=" * 80)
print("SHAPEFILE FIELD ANALYSIS")
print("=" * 80)

for name, shp_path in [("TRACKS", tracks_file), ("PRAs", pra_file), ("RISK ASSESSMENT", risk_file)]:
    if shp_path and shp_path.exists():
        print(f"\n{name}: {shp_path.name}")
        print("-" * 80)
        fields = arcpy.ListFields(str(shp_path))
        for f in fields:
            print(f"  {f.name:20s} | Type: {f.type:15s} | Length: {f.length if hasattr(f, 'length') else 'N/A'}")
    else:
        print(f"\n{name}: NOT FOUND")

print("\n" + "=" * 80)
