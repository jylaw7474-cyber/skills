# plan-to-3d

Turns a plotted 2D architectural sheet (DWF / DWFx) into a measured 3D model of
the apartments it draws, plus a self-contained interactive viewer.

```bash
pip install numpy scipy pillow

python scripts/dwfx_extract.py  plan.dwfx --out extract/
python scripts/plan_to_model.py extract/  --out model.json \
        --zone-colors '#C0C0C0,#AAE197' --line-colors '#000000,#0000FF'
python scripts/preview_plan.py  model.json --index 1 --out preview.png   # sanity check
python scripts/build_viewer.py  model.json --out apartments.html
```

`SKILL.md` documents the stages, the flags, and - importantly - how to read the
result honestly: which numbers come straight from the drawing and which are
reconstructed.
