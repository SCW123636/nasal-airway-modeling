"""T-039 step 2b probe: dump EM API surface + try metadata refresh (headless)."""
import sys
import slicer

em = slicer.app.extensionsManagerModel()

print("=" * 60)
print("INSTALL_PATH", em.extensionsInstallPath)
try:
    su = getattr(em, "serverUrl")
    print("SERVER_URL", su() if callable(su) else su)
except Exception as e:
    print("SERVER_URL <err>", e)
try:
    fu = getattr(em, "frontendServerUrl")
    print("FRONTEND_URL", fu() if callable(fu) else fu)
except Exception as e:
    print("FRONTEND_URL <err>", e)

print("-" * 60)
methods = [m for m in dir(em) if not m.startswith("_")]
print("METHODS:")
for m in methods:
    print("   ", m)

print("-" * 60)
for name in ("updateExtensionsMetadataFromServer", "retrieveExtensionMetadata"):
    fn = getattr(em, name, None)
    if fn is None:
        print("CALL", name, "-> NOT PRESENT")
        continue
    try:
        print("CALL", name, "->", fn())
    except Exception as e:
        print("CALL", name, "ERR", repr(e))

print("-" * 60)
try:
    model = em.model()
    n = model.rowCount()
    print("MODEL_ROWS", n)
    ids = []
    for i in range(n):
        ids.append(model.data(model.index(i, 0)))
    vmtk = [x for x in ids if x and "VMTK" in str(x).upper()]
    print("VMTK_MATCH", vmtk)
    cfdl = [x for x in ids if x and "CFD" in str(x).upper()]
    print("CFD_MATCH", cfdl)
    print("SAMPLE20", ids[:20])
except Exception as e:
    print("MODEL_ERR", repr(e))

print("=" * 60)
sys.exit(0)
