"""T-039 step 2d: install SlicerVMTK (headless) via the ExtensionManagerModel API.

Pumps the event loop while async download/extract tasks run. Logs everything so
the run is reproducible from the transcript. No GUI is involved.
"""
import sys
import time
import slicer

em = slicer.app.extensionsManagerModel()

print("=" * 70)
print("INSTALL_PATH", em.extensionsInstallPath())
print("AUTOINSTALL_DEPS", em.autoInstallDependencies)
for m in ("installExtensionFromServer", "downloadAndInstallExtensionByName",
          "downloadAndInstallExtension", "installExtension",
          "extractExtensionArchive", "waitForAllTasksCompletion",
          "isExtensionInstalled", "extensionMetadata"):
    try:
        print("HELP %-32s %s" % (m, em.help(m)))
    except Exception as e:
        print("HELP %-32s <err> %r" % (m, e))

print("-" * 70)
# --- make sure metadata is loaded into the model ---
done = {"v": False}
em.updateExtensionsMetadataFromServerCompleted.connect(lambda *a: done.__setitem__("v", True))
em.updateExtensionsMetadataFromServer()
t0 = time.time()
while not done["v"] and time.time() - t0 < 120:
    slicer.app.processEvents()
    time.sleep(0.05)
slicer.app.processEvents()
try:
    em.updateModel()
    slicer.app.processEvents()
except Exception as e:
    print("updateModel ERR", repr(e))

model = em.model()
print("MODEL_ROWS", model.rowCount())
try:
    md = em.extensionMetadata("SlicerVMTK")
    print("METADATA_SlicerVMTK_KEYS", sorted(md.keys()) if md else md)
except Exception as e:
    print("extensionMetadata ERR", repr(e))

print("-" * 70)
print("PRE_INSTALLED", em.isExtensionInstalled("SlicerVMTK"))

# --- install: try the API variants in order of preference ---
res = None
for label, call in (
    ("installExtensionFromServer('SlicerVMTK')", lambda: em.installExtensionFromServer("SlicerVMTK")),
    ("downloadAndInstallExtensionByName('SlicerVMTK', True)",
     lambda: em.downloadAndInstallExtensionByName("SlicerVMTK", True)),
    ("downloadAndInstallExtension('SlicerVMTK', True)",
     lambda: em.downloadAndInstallExtension("SlicerVMTK", True)),
):
    try:
        res = call()
        print("INSTALL_CALL %s -> %r" % (label, res))
        break
    except Exception as e:
        print("INSTALL_CALL %s ERR %r" % (label, e))

# --- pump until tasks drain (bounded) ---
t0 = time.time()
last = None
while time.time() - t0 < 420:
    slicer.app.processEvents()
    time.sleep(0.1)
    try:
        tasks = em.activeTasks()
        n = len(tasks) if tasks is not None else 0
    except Exception:
        n = -1
    if n != last:
        print("  t=%5.1fs activeTasks=%s installed=%s" % (time.time() - t0, n,
                                                          em.isExtensionInstalled("SlicerVMTK")))
        last = n
    if n == 0 and time.time() - t0 > 15:
        break

print("-" * 70)
print("POST_INSTALLED", em.isExtensionInstalled("SlicerVMTK"))
print("INSTALLED_LIST", em.installedExtensions())
print("MODULE_PATHS", em.extensionModulePaths("SlicerVMTK"))
print("=" * 70)
sys.exit(0)
