import slicer

image_path = r"D:\项目\鼻腔建模\NasalSeg_按患者\P001\P001_img.nrrd"
label_path = r"D:\项目\鼻腔建模\NasalSeg_按患者\P001\P001_seg.nrrd"
log_path = r"D:\项目\鼻腔建模\work\验证_NasalSeg_P001_Slicer.log"
scene_path = r"D:\项目\鼻腔建模\work\NasalSeg_P001_Slicer场景.mrml"

lines = []
try:
    image_ok, image_node = slicer.util.loadVolume(image_path, returnNode=True)
    label_ok, label_node = slicer.util.loadLabelVolume(label_path, returnNode=True)
    if not image_ok or image_node is None:
        raise RuntimeError("image load failed")
    if not label_ok or label_node is None:
        raise RuntimeError("label load failed")

    image_data = image_node.GetImageData()
    label_data = label_node.GetImageData()
    if image_data is None or label_data is None:
        raise RuntimeError("loaded node has no image data")

    lines = [
        "NasalSeg P001 Slicer load: OK",
        "IMAGE_NODE=" + image_node.GetName(),
        "IMAGE_DIMS=" + str(image_data.GetDimensions()),
        "IMAGE_RANGE=" + str(image_data.GetScalarRange()),
        "LABEL_NODE=" + label_node.GetName(),
        "LABEL_DIMS=" + str(label_data.GetDimensions()),
        "LABEL_RANGE=" + str(label_data.GetScalarRange()),
    ]
    if not slicer.util.saveScene(scene_path):
        raise RuntimeError("scene save failed")
    lines.append("SCENE=" + scene_path)
except Exception as exc:
    lines = ["NasalSeg P001 Slicer load: FAILED", repr(exc)]

with open(log_path, "w") as log_file:
    log_file.write("\n".join(lines) + "\n")
print("\n".join(lines))
slicer.util.exit()
