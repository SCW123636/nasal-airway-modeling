"""T-039 step 2c: refresh extension metadata with event loop, then dump the catalog
rows so we can identify the exact VMTK extension id/name for headless install."""
import sys
import time
import slicer

em = slicer.app.extensionsManagerModel()

done = {"v": False}


def _on_done(*a, **k):
    done["v"] = True


try:
    em.updateExtensionsMetadataFromServerCompleted.connect(_on_done)
except Exception as e:
    print("CONNECT_ERR", repr(e))

t0 = time.time()
print("UPDATE_RET", em.updateExtensionsMetadataFromServer())
while not done["v"] and time.time() - t0 < 120:
    slicer.app.processEvents()
    time.sleep(0.05)

print("WAITED_S", round(time.time() - t0, 2), "COMPLETED", done["v"])
slicer.app.processEvents()

model = em.model()
rows = model.rowCount()
cols = model.columnCount()
print("MODEL", rows, "rows x", cols, "cols")

hdr = []
for c in range(cols):
    hdr.append(str(model.headerData(c, 1)))  # 1 = Qt.Horizontal
print("HEADERS", hdr)

print("-" * 60)
for i in range(rows):
    cells = [str(model.data(model.index(i, c))) for c in range(cols)]
    joined = " | ".join(cells)
    if "VMTK" in joined.upper() or "SIMVASCULAR" in joined.upper() or "CFD" in joined.upper():
        print("HIT", joined)

print("-" * 60)
print("ALL_NAMES_FIRST_COL")
for i in range(rows):
    print("   ", str(model.data(model.index(i, 0))))

print("=" * 60)
sys.exit(0)
