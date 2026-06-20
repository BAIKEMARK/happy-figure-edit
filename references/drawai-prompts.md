# DrawAI Prompt Lessons for Happy Figure Edit

Study these ideas when improving Expert prompts:

- Split the workflow into asset parsing, asset post-processing, and editable reconstruction.
- Use `box_id` to connect candidates, OCR text, asset decisions, SVG elements, and PPTX objects.
- Use `svg_self_draw` for editable structure, `crop` for exact raster regions, and `crop_nobg` for transparent foreground cutouts.
- Treat original image evidence as higher priority than OCR, segmentation, or template IR.
- Use manifest allowlists for every raster image href in SVG.
- Prefer box-level retry over whole-image retry when reducing cost.

Do not copy DrawAI runtime prompts directly. Rewrite prompts around Happy Figure Edit schema and budget modes.
