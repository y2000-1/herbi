/**
 * EXIF Orientation Correction Utility
 *
 * Solves the classic iOS Safari bug: photos taken with iPhone/iPad
 * have EXIF orientation metadata that browsers ignore when displaying
 * <img>, but NOT when rendering to <canvas> or uploading raw.
 *
 * This module reads the EXIF orientation tag from JPEG files and
 * applies the correct canvas rotation/flip before creating a properly
 * oriented Blob for upload.
 *
 * Compatible with all mobile and desktop browsers.
 */

const EXIF = (function () {
    'use strict';

    /**
     * Read EXIF orientation from a JPEG file (raw bytes / ArrayBuffer).
     *
     * @param {ArrayBuffer|Uint8Array} data - Raw JPEG bytes
     * @returns {number} EXIF orientation value (1-8), or 1 (normal) if not found.
     *
     * Orientation values:
     *   1 = Normal (no transform)
     *   2 = Flip horizontal
     *   3 = Rotate 180°
     *   4 = Flip vertical
     *   5 = Rotate 90° CW + flip horizontal
     *   6 = Rotate 90° CW ← Most common iPhone/iPad case
     *   7 = Rotate 90° CCW + flip horizontal
     *   8 = Rotate 90° CCW
     */
    function getOrientation(data) {
        if (data instanceof ArrayBuffer) {
            data = new Uint8Array(data);
        }

        // Must be JPEG
        if (data.length < 2 || data[0] !== 0xFF || data[1] !== 0xD8) {
            return 1;
        }

        let offset = 2;
        const length = data.length;

        while (offset < length) {
            // Look for markers
            if (data[offset] !== 0xFF) {
                break;
            }

            const marker = data[offset + 1];

            // SOS (Start of Scan) — we've gone past metadata
            if (marker === 0xDA) {
                break;
            }

            // APP1 marker (EXIF data)
            if (marker === 0xE1) {
                const exifLength = (data[offset + 2] << 8) | data[offset + 3];
                const exifStart = offset + 4;

                // Check for "Exif\0\0" header
                if (exifStart + 6 <= length &&
                    data[exifStart] === 0x45 && // 'E'
                    data[exifStart + 1] === 0x78 && // 'x'
                    data[exifStart + 2] === 0x69 && // 'i'
                    data[exifStart + 3] === 0x66 && // 'f'
                    data[exifStart + 4] === 0x00 &&
                    data[exifStart + 5] === 0x00) {

                    return parseExifOrientation(data, exifStart + 6, exifLength - 6);
                }
                // Marker handled
                offset = offset + 2 + exifLength;
                continue;
            }

            // Skip other markers
            if (marker >= 0xC0 && marker <= 0xFE) {
                offset += 2 + ((data[offset + 2] << 8) | data[offset + 3]);
            } else {
                offset += 2;
            }
        }

        return 1; // Default: normal orientation
    }

    /**
     * Walk TIFF/EXIF IFDs to find Orientation tag (0x0112).
     */
    function parseExifOrientation(data, start, _length) {
        // Byte order: 'II' (little-endian) or 'MM' (big-endian)
        const littleEndian = data[start] === 0x49 && data[start + 1] === 0x49;

        function readU16(offset) {
            const b = data[offset];
            const b2 = data[offset + 1];
            return littleEndian ? (b2 << 8) | b : (b << 8) | b2;
        }

        function readU32(offset) {
            const b0 = data[offset];
            const b1 = data[offset + 1];
            const b2 = data[offset + 2];
            const b3 = data[offset + 3];
            return littleEndian
                ? (b3 << 24) | (b2 << 16) | (b1 << 8) | b0
                : (b0 << 24) | (b1 << 16) | (b2 << 8) | b3;
        }

        // Check TIFF magic number (0x002A)
        if (readU16(start + 2) !== 0x002A) {
            return 1;
        }

        // First IFD offset
        let ifdOffset = start + readU32(start + 4);
        if (ifdOffset + 2 > data.length) {
            return 1;
        }

        const numEntries = readU16(ifdOffset);
        ifdOffset += 2;

        for (let i = 0; i < numEntries; i++) {
            if (ifdOffset + 12 > data.length) {
                break;
            }

            const tag = readU16(ifdOffset);
            if (tag === 0x0112) { // Orientation tag
                const orientVal = readU16(ifdOffset + 8);
                return orientVal >= 1 && orientVal <= 8 ? orientVal : 1;
            }

            ifdOffset += 12;
        }

        return 1;
    }

    /**
     * Apply EXIF orientation correction to an image and return a Blob.
     *
     * The corrected image is re-encoded as JPEG at the specified quality.
     * Non-JPEG input (PNG, WebP, etc.) is returned unchanged since those
     * formats don't use EXIF orientation.
     *
     * @param {File|Blob} file - The original image file
     * @param {number} [quality=0.92] - JPEG quality for re-encoding (0-1)
     * @returns {Promise<{blob: Blob, wasCorrected: boolean}>}
     */
    async function correctOrientation(file, quality) {
        quality = quality || 0.92;

        // Only JPEG files can have EXIF orientation
        const isJPEG = file.type === 'image/jpeg' ||
                       file.type === 'image/jpg' ||
                       /\.jpe?g$/i.test(file.name || '');

        if (!isJPEG) {
            return { blob: file, wasCorrected: false };
        }

        try {
            const arrayBuffer = await readFileAsArrayBuffer(file);
            const orientation = getOrientation(new Uint8Array(arrayBuffer));

            // No correction needed
            if (orientation === 1) {
                return { blob: file, wasCorrected: false };
            }

            // Apply correction via canvas
            const correctedBlob = await applyOrientationFix(arrayBuffer, orientation, quality);
            return { blob: correctedBlob, wasCorrected: true };
        } catch (e) {
            // On any error, return original file
            console.warn('EXIF correction failed, using original:', e);
            return { blob: file, wasCorrected: false };
        }
    }

    /**
     * Apply rotation/flip to correct EXIF orientation using canvas.
     */
    function applyOrientationFix(arrayBuffer, orientation, quality) {
        return new Promise(function (resolve, reject) {
            const blob = new Blob([arrayBuffer], { type: 'image/jpeg' });
            const url = URL.createObjectURL(blob);
            const img = new Image();

            img.onload = function () {
                URL.revokeObjectURL(url);

                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');

                // Set canvas dimensions based on orientation
                let width = img.width;
                let height = img.height;

                if (orientation >= 5 && orientation <= 8) {
                    // Swap dimensions for 90° rotations
                    canvas.width = height;
                    canvas.height = width;
                } else {
                    canvas.width = width;
                    canvas.height = height;
                }

                // Apply transforms based on EXIF orientation
                ctx.save();
                switch (orientation) {
                    case 2: // Flip horizontal
                        ctx.translate(width, 0);
                        ctx.scale(-1, 1);
                        break;
                    case 3: // Rotate 180°
                        ctx.translate(width, height);
                        ctx.rotate(Math.PI);
                        break;
                    case 4: // Flip vertical
                        ctx.translate(0, height);
                        ctx.scale(1, -1);
                        break;
                    case 5: // Rotate 90° CW + flip horizontal
                        ctx.rotate(0.5 * Math.PI);
                        ctx.scale(1, -1);
                        break;
                    case 6: // Rotate 90° CW (most common for iPhone)
                        ctx.rotate(0.5 * Math.PI);
                        ctx.translate(0, -height);
                        break;
                    case 7: // Rotate 90° CCW + flip horizontal
                        ctx.rotate(-0.5 * Math.PI);
                        ctx.translate(-width, 0);
                        ctx.scale(1, -1);
                        break;
                    case 8: // Rotate 90° CCW
                        ctx.rotate(-0.5 * Math.PI);
                        ctx.translate(-width, 0);
                        break;
                    default:
                        // No transform
                        break;
                }

                ctx.drawImage(img, 0, 0, width, height);
                ctx.restore();

                canvas.toBlob(function (correctedBlob) {
                    if (correctedBlob) {
                        resolve(correctedBlob);
                    } else {
                        reject(new Error('Canvas toBlob failed'));
                    }
                }, 'image/jpeg', quality);
            };

            img.onerror = function () {
                URL.revokeObjectURL(url);
                reject(new Error('Failed to load image for orientation fix'));
            };

            img.src = url;
        });
    }

    function readFileAsArrayBuffer(file) {
        return new Promise(function (resolve, reject) {
            const reader = new FileReader();
            reader.onload = function () { resolve(reader.result); };
            reader.onerror = function () { reject(reader.error); };
            reader.readAsArrayBuffer(file);
        });
    }

    // Public API
    return {
        getOrientation: getOrientation,
        correctOrientation: correctOrientation,
    };
})();
