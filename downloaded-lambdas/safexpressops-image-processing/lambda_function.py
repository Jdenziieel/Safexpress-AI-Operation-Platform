"""
Lambda Function: Image Processor with PyMuPDF
Dedicated function for extracting images from PDFs using PyMuPDF.
Invoked by main Lambda when design-heavy PDFs are detected.
"""

import json
import base64
import io
import fitz  # PyMuPDF


def extract_images_with_pymupdf(file_bytes: bytes, page_number: int) -> list:
    """
    Extract images from a PDF page using PyMuPDF.

    Args:
        file_bytes: PDF file content as bytes
        page_number: Zero-indexed page number

    Returns:
        List of image dicts with id, type, box, page, and image_b64
    """
    images = []

    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            if page_number >= len(doc):
                return images

            page = doc[page_number]
            xref_rows = page.get_images(full=True)

            if not xref_rows:
                return images

            for img_index, row in enumerate(xref_rows):
                xref = row[0]
                rects = page.get_image_rects(xref)

                try:
                    pix = fitz.Pixmap(doc, xref)

                    # Convert CMYK/other color spaces to RGB
                    if pix.n > 4:
                        pix = fitz.Pixmap(fitz.csRGB, pix)

                    # Convert to base64 PNG
                    img_b64 = base64.b64encode(pix.tobytes("png")).decode("utf-8")

                except Exception as e:
                    print(f"[WARN] xref={xref} pixmap failed: {e}")
                    continue

                # Handle multiple placements of same image
                for placement_idx, rect in enumerate(rects):
                    l, t, r, b = rect.x0, rect.y0, rect.x1, rect.y1
                    unique_image_id = (
                        f"p{page_number+1}-img-{img_index}-{placement_idx}"
                    )

                    images.append(
                        {
                            "id": unique_image_id,
                            "type": "image",
                            "subtype": "embedded",
                            "box": {"l": l, "t": t, "r": r, "b": b},
                            "page": page_number + 1,
                            "image_b64": img_b64,
                        }
                    )

    except Exception as e:
        print(f"[ERROR] Failed to process page {page_number}: {e}")
        return []

    return images


def lambda_handler(event, context):
    """
    AWS Lambda handler for image extraction.

    Expected event structure:
    {
        "file_bytes_base64": "base64 encoded PDF",
        "page_numbers": [0, 1, 2],  # Optional, defaults to all pages
        "operation": "extract_images"
    }

    Returns:
    {
        "statusCode": 200,
        "body": {
            "images": [...],
            "total_images": 10,
            "pages_processed": 3
        }
    }
    """
    try:
        # Parse input
        if isinstance(event.get("body"), str):
            body = json.loads(event["body"])
        else:
            body = event

        operation = body.get("operation", "extract_images")

        if operation != "extract_images":
            return {
                "statusCode": 400,
                "body": json.dumps({"error": f"Unsupported operation: {operation}"}),
            }

        # Decode PDF bytes
        file_bytes_base64 = body.get("file_bytes_base64")
        if not file_bytes_base64:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing file_bytes_base64"}),
            }

        file_bytes = base64.b64decode(file_bytes_base64)

        # Get page numbers to process
        page_numbers = body.get("page_numbers", None)

        # If no specific pages, extract from all pages
        all_images = []

        if page_numbers is None:
            # Process all pages
            with fitz.open(stream=file_bytes, filetype="pdf") as doc:
                page_numbers = list(range(len(doc)))

        # Extract images from specified pages
        for page_num in page_numbers:
            page_images = extract_images_with_pymupdf(file_bytes, page_num)
            all_images.extend(page_images)

        print(
            f"[INFO] Extracted {len(all_images)} images from {len(page_numbers)} pages"
        )

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "images": all_images,
                    "total_images": len(all_images),
                    "pages_processed": len(page_numbers),
                }
            ),
        }

    except Exception as e:
        import traceback

        error_trace = traceback.format_exc()
        print(f"[ERROR] Lambda execution failed: {error_trace}")

        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e), "trace": error_trace}),
        }
