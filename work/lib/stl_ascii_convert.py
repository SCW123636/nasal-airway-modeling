# -*- coding: utf-8 -*-
"""Write an ASCII STL (optionally decimated) from a binary STL.

Used to isolate whether the Netgen STL mesher's failure on the patient surface
is about the encoding or about the geometry itself.
"""
import argparse
from pathlib import Path

import vtk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('source')
    ap.add_argument('out')
    ap.add_argument('--decimate', type=float, default=None,
                    help='target fraction of triangles, e.g. 0.02')
    args = ap.parse_args()

    reader = vtk.vtkSTLReader()
    reader.SetFileName(str(args.source))
    reader.Update()
    poly = reader.GetOutput()
    print('read triangles:', poly.GetNumberOfCells())

    if args.decimate:
        dec = vtk.vtkQuadricDecimation()
        dec.SetInputData(poly)
        dec.SetTargetReduction(1.0 - args.decimate)
        dec.Update()
        poly = dec.GetOutput()
        print('decimated triangles:', poly.GetNumberOfCells())

    writer = vtk.vtkSTLWriter()
    writer.SetFileName(str(args.out))
    writer.SetFileTypeToASCII()
    writer.SetInputData(poly)
    writer.Write()
    print('wrote', args.out, Path(args.out).stat().st_size, 'bytes')


if __name__ == '__main__':
    main()
