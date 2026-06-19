/**
 * HerbiEstim API Client
 *
 * Handles communication with the backend FastAPI service.
 * Uses fetch() with FormData — compatible with all browsers
 * including mobile and WeChat in-app browser.
 */

const HerbiAPI = (function () {
    'use strict';

    /**
     * Get the API base URL.
     * Auto-detects: same-origin (served by backend) or configurable.
     */
    function getBaseURL() {
        // Check for explicit config
        if (window.HERBI_API_URL) {
            return window.HERBI_API_URL.replace(/\/+$/, '');
        }

        // Same-origin default (backend serves frontend)
        return window.location.origin;
    }

    /**
     * Check API health status.
     *
     * @returns {Promise<{status: string, pix2pix_loaded: boolean, sam_loaded: boolean, gpu_available: boolean}>}
     */
    async function healthCheck() {
        const base = getBaseURL();
        const response = await fetch(base + '/api/v1/health', {
            method: 'GET',
            headers: { 'Accept': 'application/json' },
        });

        if (!response.ok) {
            throw new Error('Health check failed: ' + response.status);
        }

        return response.json();
    }

    /**
     * Analyze a leaf image for herbivore damage.
     *
     * @param {Object} params
     * @param {File|Blob} params.image - The image file to analyze
     * @param {number} [params.dpi=300] - DPI for area calculation
     * @param {boolean} [params.useSam=false] - Use SAM segmentation
     * @param {boolean} [params.isScanned=true] - Whether image is from a scanner
     * @param {boolean} [params.returnImages=true] - Include base64 images in response
     * @param {boolean} [params.debug=false] - Enable debug visualizations
     * @param {function} [params.onProgress] - Progress callback (0-100)
     * @returns {Promise<Object>} Analysis results matching AnalyzeResponse schema
     */
    async function analyzeImage(params) {
        var image = params.image;
        var dpi = params.dpi || 300;
        var useSam = params.useSam || false;
        var isScanned = params.isScanned !== false; // default true
        var returnImages = params.returnImages !== false; // default true
        var debug = params.debug || false;
        var onProgress = params.onProgress || null;

        var base = getBaseURL();
        var formData = new FormData();

        // Append image — use a filename that preserves extension for detection
        var filename = image.name || 'leaf.jpg';
        formData.append('image', image, filename);
        formData.append('dpi', String(dpi));
        formData.append('use_sam', useSam ? 'true' : 'false');
        formData.append('is_scanned', isScanned ? 'true' : 'false');
        formData.append('return_images', returnImages ? 'true' : 'false');
        formData.append('debug', debug ? 'true' : 'false');

        // Progress simulation for better UX (fetch doesn't support upload progress natively)
        if (onProgress) {
            onProgress(10); // Started upload
        }

        // Use XMLHttpRequest to support progress tracking
        return new Promise(function (resolve, reject) {
            var xhr = new XMLHttpRequest();

            xhr.open('POST', base + '/api/v1/analyze', true);

            // Don't set Content-Type — browser will set it with boundary
            xhr.setRequestHeader('Accept', 'application/json');

            // Upload progress
            if (onProgress && xhr.upload) {
                xhr.upload.onprogress = function (e) {
                    if (e.lengthComputable) {
                        // Upload is ~0-50% of total
                        var pct = Math.round(10 + (e.loaded / e.total) * 40);
                        onProgress(pct);
                    }
                };
            }

            xhr.onload = function () {
                if (onProgress) {
                    onProgress(90); // Processing complete, parsing
                }

                if (xhr.status >= 200 && xhr.status < 300) {
                    try {
                        var result = JSON.parse(xhr.responseText);
                        if (onProgress) {
                            onProgress(100);
                        }
                        resolve(result);
                    } catch (e) {
                        reject(new Error('Failed to parse server response'));
                    }
                } else {
                    var detail = 'Server error: ' + xhr.status;
                    try {
                        var errData = JSON.parse(xhr.responseText);
                        if (errData.detail) {
                            detail = errData.detail;
                        }
                    } catch (_) {}
                    reject(new Error(detail));
                }
            };

            xhr.onerror = function () {
                reject(new Error('Network error. Please check your connection and try again.'));
            };

            xhr.ontimeout = function () {
                reject(new Error('Request timed out. The image may be too large or the server is busy.'));
            };

            xhr.timeout = 120000; // 2 minute timeout — leaf analysis can be slow on CPU

            if (onProgress) {
                onProgress(15); // Sending
            }

            xhr.send(formData);
        });
    }

    // Public API
    return {
        healthCheck: healthCheck,
        analyzeImage: analyzeImage,
    };
})();
