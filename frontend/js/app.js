/**
 * HerbiEstim Frontend Application
 *
 * Cross-platform mobile-first SPA for leaf herbivore damage estimation.
 * Pure vanilla JavaScript — no framework dependencies.
 *
 * Compatible with:
 *   Desktop: Chrome, Edge, Safari, Firefox (Windows / macOS / Linux)
 *   Mobile: Android Chrome/System/QQ/UC,
 *           iOS Safari, WeChat in-app browser
 */

(function () {
    'use strict';

    // =========================================================================
    // DOM References (cached on init)
    // =========================================================================
    var els = {};

    function cacheDOM() {
        els.themeToggle = document.getElementById('themeToggle');
        els.uploadArea = document.getElementById('uploadArea');
        els.fileInput = document.getElementById('fileInput');
        els.previewContainer = document.getElementById('previewContainer');
        els.previewImage = document.getElementById('previewImage');
        els.clearPreview = document.getElementById('clearPreview');
        els.analyzeBtn = document.getElementById('analyzeBtn');
        els.dpiInput = document.getElementById('dpiInput');
        els.scannedToggle = document.getElementById('scannedToggle');
        els.samToggle = document.getElementById('samToggle');
        els.statusSection = document.getElementById('statusSection');
        els.progressBar = document.getElementById('progressBar');
        els.statusText = document.getElementById('statusText');
        els.errorSection = document.getElementById('errorSection');
        els.errorMessage = document.getElementById('errorMessage');
        els.dismissError = document.getElementById('dismissError');
        els.summarySection = document.getElementById('summarySection');
        els.summaryLeaves = document.getElementById('summaryLeaves');
        els.summaryDamage = document.getElementById('summaryDamage');
        els.summaryLeafArea = document.getElementById('summaryLeafArea');
        els.summaryIntactArea = document.getElementById('summaryIntactArea');
        els.leavesSection = document.getElementById('leavesSection');
        els.leavesContainer = document.getElementById('leavesContainer');
        els.toastContainer = document.getElementById('toastContainer');
        els.loadingSpinner = document.getElementById('loadingSpinner');
    }

    // =========================================================================
    // State
    // =========================================================================
    var state = {
        selectedFile: null,
        isAnalyzing: false,
        theme: 'light',
    };

    // =========================================================================
    // Theme Management
    // =========================================================================
    function initTheme() {
        // Check saved preference, then system preference
        var saved = localStorage.getItem('herbiestim-theme');
        if (saved === 'dark' || saved === 'light') {
            state.theme = saved;
        } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            state.theme = 'dark';
        }
        applyTheme();

        // Listen for system theme changes
        if (window.matchMedia) {
            window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function (e) {
                if (!localStorage.getItem('herbiestim-theme')) {
                    state.theme = e.matches ? 'dark' : 'light';
                    applyTheme();
                }
            });
        }
    }

    function toggleTheme() {
        state.theme = state.theme === 'dark' ? 'light' : 'dark';
        localStorage.setItem('herbiestim-theme', state.theme);
        applyTheme();
    }

    function applyTheme() {
        document.documentElement.setAttribute('data-theme', state.theme);
    }

    // =========================================================================
    // Toast Notifications
    // =========================================================================
    function showToast(message, type, duration) {
        type = type || 'info';
        duration = duration || 3000;

        var toast = document.createElement('div');
        toast.className = 'toast toast-' + type;
        toast.textContent = message;
        els.toastContainer.appendChild(toast);

        setTimeout(function () {
            toast.classList.add('fade-out');
            setTimeout(function () {
                if (toast.parentNode) {
                    toast.parentNode.removeChild(toast);
                }
            }, 300);
        }, duration);
    }

    // =========================================================================
    // File Upload & Preview
    // =========================================================================
    function handleFileSelect(event) {
        var files = event.target.files;
        if (!files || files.length === 0) {
            return;
        }
        setSelectedFile(files[0]);
    }

    function setSelectedFile(file) {
        // Validate file type
        var validTypes = ['image/jpeg', 'image/jpg', 'image/png',
                          'image/tiff', 'image/bmp', 'image/webp'];
        var validExtensions = ['.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp', '.webp'];

        var isImage = validTypes.indexOf(file.type) !== -1;
        if (!isImage) {
            var name = (file.name || '').toLowerCase();
            isImage = validExtensions.some(function (ext) {
                return name.endsWith(ext);
            });
        }

        if (!isImage) {
            showToast('请选择图片文件（JPG / PNG / TIFF / BMP / WebP）', 'error');
            return;
        }

        // Validate file size (max 20MB client-side check)
        var maxSize = 20 * 1024 * 1024;
        if (file.size > maxSize) {
            showToast('图片文件过大，请选择小于 20MB 的图片', 'error');
            return;
        }

        state.selectedFile = file;
        els.analyzeBtn.disabled = false;
        showPreview(file);
    }

    function showPreview(file) {
        var reader = new FileReader();
        reader.onload = function (e) {
            els.previewImage.src = e.target.result;
            els.previewContainer.classList.remove('hidden');
            // Scroll to preview
            els.previewContainer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        };
        reader.readAsDataURL(file);
    }

    function clearSelection() {
        state.selectedFile = null;
        els.fileInput.value = '';
        els.previewContainer.classList.add('hidden');
        els.previewImage.src = '';
        els.analyzeBtn.disabled = true;
    }

    // =========================================================================
    // Analysis
    // =========================================================================
    async function startAnalysis() {
        if (!state.selectedFile || state.isAnalyzing) {
            return;
        }

        state.isAnalyzing = true;
        els.analyzeBtn.disabled = true;

        // Hide previous results
        els.errorSection.classList.add('hidden');
        els.summarySection.classList.add('hidden');
        els.leavesSection.classList.add('hidden');

        // Show status
        els.statusSection.classList.remove('hidden');
        els.statusText.textContent = '正在准备图片...';
        els.progressBar.style.width = '0%';
        els.loadingSpinner.style.display = 'block';

        try {
            // Step 1: EXIF orientation correction (for iOS photos)
            updateStatus('正在校正图片方向...', 5);
            var exifResult = await EXIF.correctOrientation(state.selectedFile, 0.92);
            if (exifResult.wasCorrected) {
                updateStatus('已校正图片方向 (EXIF)', 8);
            }

            // Step 2: Read form values
            var dpi = parseInt(els.dpiInput.value) || 300;
            var isScanned = els.scannedToggle.checked;
            var useSam = els.samToggle.checked;

            // Step 3: Call API
            updateStatus('正在上传图片...', 10);

            var result = await HerbiAPI.analyzeImage({
                image: exifResult.blob,
                dpi: dpi,
                useSam: useSam,
                isScanned: isScanned,
                returnImages: true,
                debug: false,
                onProgress: function (pct) {
                    updateProgress(pct);
                    if (pct < 30) {
                        updateStatus('正在上传图片...', null);
                    } else if (pct < 70) {
                        updateStatus('正在AI分析中...', null);
                    } else if (pct < 95) {
                        updateStatus('正在计算损伤面积...', null);
                    } else {
                        updateStatus('分析完成，正在生成结果...', null);
                    }
                },
            });

            // Step 4: Render results
            updateStatus('正在渲染结果...', 95);
            renderResults(result);

            // Hide status after short delay
            setTimeout(function () {
                els.statusSection.classList.add('hidden');
            }, 500);

            var numLeaves = result.summary ? result.summary.num_leaves : 0;
            showToast('分析完成！检测到 ' + numLeaves + ' 片叶片', 'success');

        } catch (error) {
            els.statusSection.classList.add('hidden');
            showError(error.message || '分析失败，请重试');
            showToast('分析失败: ' + (error.message || '未知错误'), 'error');
        } finally {
            state.isAnalyzing = false;
            els.analyzeBtn.disabled = !state.selectedFile;
        }
    }

    function updateStatus(message, _pct) {
        els.statusText.textContent = message;
    }

    function updateProgress(pct) {
        els.progressBar.style.width = pct + '%';
    }

    // =========================================================================
    // Error Display
    // =========================================================================
    function showError(message) {
        els.errorMessage.textContent = message;
        els.errorSection.classList.remove('hidden');
        els.errorSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    function dismissError() {
        els.errorSection.classList.add('hidden');
    }

    // =========================================================================
    // Results Rendering
    // =========================================================================
    function renderResults(result) {
        var summary = result.summary || {};
        var leaves = result.leaves || [];

        // ── Summary ──────────────────────────────────────────────────
        els.summaryLeaves.textContent = summary.num_leaves || 0;
        var avgDamage = (summary.avg_damage_pct !== undefined && summary.avg_damage_pct !== null)
            ? (summary.avg_damage_pct * 100).toFixed(1) + '%'
            : '--';
        els.summaryDamage.textContent = avgDamage;

        if (summary.total_leaf_area_cm2 !== null && summary.total_leaf_area_cm2 !== undefined) {
            els.summaryLeafArea.textContent = Number(summary.total_leaf_area_cm2).toFixed(2) + ' cm²';
            els.summaryIntactArea.textContent = Number(summary.total_intact_area_cm2).toFixed(2) + ' cm²';
        } else {
            els.summaryLeafArea.textContent = '--';
            els.summaryIntactArea.textContent = '--';
        }
        els.summarySection.classList.remove('hidden');

        // ── Per-Leaf Cards ───────────────────────────────────────────
        els.leavesContainer.innerHTML = '';

        if (leaves.length === 0) {
            els.leavesContainer.innerHTML = '<div class="card" style="text-align:center;color:var(--color-text-muted);"><p>未检测到叶片</p><p style="font-size:var(--font-size-xs)">请确认图片中包含清晰的叶片</p></div>';
        }

        leaves.forEach(function (leaf, index) {
            var card = createLeafCard(leaf, index);
            els.leavesContainer.appendChild(card);
        });

        els.leavesSection.classList.remove('hidden');

        // Scroll to summary
        els.summarySection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function createLeafCard(leaf, index) {
        var card = document.createElement('div');
        card.className = 'leaf-card';

        // Determine damage level
        var damagePct = leaf.damage_pct || 0;
        var damageLevel = getDamageLevel(damagePct);
        var damageLabel = getDamageLabel(damagePct);

        // Area display
        var leafAreaText = leaf.leaf_area_cm2 !== null && leaf.leaf_area_cm2 !== undefined
            ? Number(leaf.leaf_area_cm2).toFixed(2) + ' cm²'
            : '--';
        var intactAreaText = leaf.intact_area_cm2 !== null && leaf.intact_area_cm2 !== undefined
            ? Number(leaf.intact_area_cm2).toFixed(2) + ' cm²'
            : '--';

        // Build HTML
        var html = '';
        html += '<div class="leaf-card-header">';
        html += '<span class="leaf-card-title">叶片 #' + (leaf.leaf_id + 1) + '</span>';
        html += '<span class="leaf-damage-badge ' + damageLevel + '">' + damageLabel + '</span>';
        html += '</div>';

        // Comparison view with lazy loading
        html += '<div class="comparison-container">';
        html += '<div class="comparison-panel">';
        html += '<div class="comparison-label damaged">🔴 受损叶片</div>';
        if (leaf.standardized_image) {
            html += '<img class="comparison-image lazy-image" ' +
                    'src="data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' viewBox=\'0 0 256 256\'%3E%3Crect fill=\'%23eee\' width=\'256\' height=\'256\'/%3E%3C/svg%3E" ' +
                    'data-src="data:image/png;base64,' + leaf.standardized_image + '" ' +
                    'alt="受损叶片" loading="lazy">';
        } else {
            html += '<div class="comparison-image" style="display:flex;align-items:center;justify-content:center;color:var(--color-text-muted)">无图像</div>';
        }
        html += '</div>';

        html += '<div class="comparison-panel">';
        html += '<div class="comparison-label reconstructed">🟢 AI复原</div>';
        if (leaf.reconstructed_image) {
            html += '<img class="comparison-image lazy-image" ' +
                    'src="data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' viewBox=\'0 0 256 256\'%3E%3Crect fill=\'%23eee\' width=\'256\' height=\'256\'/%3E%3C/svg%3E" ' +
                    'data-src="data:image/png;base64,' + leaf.reconstructed_image + '" ' +
                    'alt="AI复原叶片" loading="lazy">';
        } else {
            html += '<div class="comparison-image" style="display:flex;align-items:center;justify-content:center;color:var(--color-text-muted)">无图像</div>';
        }
        html += '</div>';
        html += '</div>';

        // Metrics
        html += '<div class="leaf-metrics">';
        html += '<div class="metric-item">';
        html += '<span class="metric-value">' + leafAreaText + '</span>';
        html += '<span class="metric-label">受损面积</span>';
        html += '</div>';
        html += '<div class="metric-item">';
        html += '<span class="metric-value">' + intactAreaText + '</span>';
        html += '<span class="metric-label">完整面积</span>';
        html += '</div>';
        html += '<div class="metric-item">';
        html += '<span class="metric-value">' + (damagePct * 100).toFixed(1) + '%</span>';
        html += '<span class="metric-label">损伤率</span>';
        html += '</div>';
        html += '</div>';

        card.innerHTML = html;

        // Set up lazy loading for images in this card
        requestAnimationFrame(function () {
            setupLazyImages(card);
        });

        return card;
    }

    /**
     * Get damage level CSS class based on damage percentage.
     */
    function getDamageLevel(pct) {
        if (pct <= 0.01) return 'damage-none';
        if (pct <= 0.05) return 'damage-low';
        if (pct <= 0.15) return 'damage-moderate';
        if (pct <= 0.30) return 'damage-high';
        return 'damage-severe';
    }

    /**
     * Get human-readable damage label in Chinese.
     */
    function getDamageLabel(pct) {
        if (pct <= 0.01) return '几乎完好';
        if (pct <= 0.05) return '轻度损伤';
        if (pct <= 0.15) return '中度损伤';
        if (pct <= 0.30) return '较重损伤';
        return '严重损伤';
    }

    // =========================================================================
    // Lazy Loading (Intersection Observer)
    // =========================================================================
    var lazyObserver = null;

    function initLazyLoading() {
        if (!('IntersectionObserver' in window)) {
            // Fallback: load all images immediately
            document.querySelectorAll('.lazy-image').forEach(function (img) {
                loadImage(img);
            });
            return;
        }

        lazyObserver = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    loadImage(entry.target);
                    lazyObserver.unobserve(entry.target);
                }
            });
        }, {
            rootMargin: '200px', // Preload when within 200px of viewport
            threshold: 0.01,
        });
    }

    function setupLazyImages(container) {
        var images = container.querySelectorAll('.lazy-image');
        images.forEach(function (img) {
            if (lazyObserver) {
                lazyObserver.observe(img);
            } else {
                loadImage(img);
            }
        });
    }

    function loadImage(img) {
        var src = img.getAttribute('data-src');
        if (!src) return;

        img.classList.add('loading');

        // Create a temporary image to preload
        var temp = new Image();
        temp.onload = function () {
            img.src = src;
            img.classList.remove('loading');
            img.removeAttribute('data-src');
        };
        temp.onerror = function () {
            img.classList.remove('loading');
            // Leave placeholder
        };
        temp.src = src;
    }

    // =========================================================================
    // Drag & Drop Support (desktop convenience)
    // =========================================================================
    function initDragDrop() {
        var area = els.uploadArea;

        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(function (eventName) {
            area.addEventListener(eventName, preventDefaults, false);
            document.body.addEventListener(eventName, preventDefaults, false);
        });

        ['dragenter', 'dragover'].forEach(function (eventName) {
            area.addEventListener(eventName, function () {
                area.classList.add('drag-over');
            }, false);
        });

        ['dragleave', 'drop'].forEach(function (eventName) {
            area.addEventListener(eventName, function () {
                area.classList.remove('drag-over');
            }, false);
        });

        area.addEventListener('drop', function (e) {
            var files = e.dataTransfer.files;
            if (files && files.length > 0) {
                setSelectedFile(files[0]);
            }
        }, false);

        function preventDefaults(e) {
            e.preventDefault();
            e.stopPropagation();
        }
    }

    // =========================================================================
    // Touch Optimizations
    // =========================================================================
    function initTouchOptimizations() {
        // Prevent double-tap zoom on buttons (iOS Safari)
        document.querySelectorAll('button, .btn, .switch-label, .upload-area').forEach(function (el) {
            el.addEventListener('touchstart', function (e) {
                // Allow default behavior — just prevent delay
            }, { passive: true });

            // Prevent iOS 300ms click delay by using touchend for interactive elements
            // (Modern iOS Safari no longer has this delay, but WeChat might)
            el.style.touchAction = 'manipulation';
        });

        // Prevent pull-to-refresh on the page body (can interfere with scroll)
        document.body.addEventListener('touchmove', function (e) {
            // Only prevent if we're at the top AND pulling down (overscroll)
            // Otherwise let normal scrolling happen
        }, { passive: true });
    }

    // =========================================================================
    // Event Bindings
    // =========================================================================
    function bindEvents() {
        // Use click for all interactive elements (modern mobile browsers don't have 300ms delay)
        // Avoid double-binding both click and touchend which causes duplicate firings

        // Theme toggle
        els.themeToggle.addEventListener('click', toggleTheme);

        // File input
        els.fileInput.addEventListener('change', handleFileSelect);

        // Clear preview
        els.clearPreview.addEventListener('click', clearSelection);

        // Analyze button
        els.analyzeBtn.addEventListener('click', startAnalysis);

        // Dismiss error
        els.dismissError.addEventListener('click', dismissError);

        // DPI input — ensure valid range
        els.dpiInput.addEventListener('change', function () {
            var val = parseInt(els.dpiInput.value) || 300;
            els.dpiInput.value = Math.max(72, Math.min(2400, val));
        });

        // Upload area click to trigger file input
        els.uploadArea.addEventListener('click', function (e) {
            // Don't trigger if user clicked the file input itself
            if (e.target !== els.fileInput) {
                els.fileInput.click();
            }
        });

        // Keyboard shortcut: Enter to analyze when file selected
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && state.selectedFile && !state.isAnalyzing) {
                var active = document.activeElement;
                // Don't trigger if user is typing in an input
                if (!active || active.tagName === 'BODY') {
                    e.preventDefault();
                    startAnalysis();
                }
            }
        });
    }

    // =========================================================================
    // Health Check on Load
    // =========================================================================
    async function checkHealth() {
        try {
            var health = await HerbiAPI.healthCheck();
            console.log('HerbiEstim API health:', health);

            if (health.status === 'degraded') {
                showToast('服务正在加载模型中，可能需要稍等片刻...', 'info', 5000);
            }

            // Update SAM toggle availability
            if (!health.sam_loaded) {
                els.samToggle.disabled = true;
                els.samToggle.parentElement.style.opacity = '0.5';
                els.samToggle.parentElement.title = 'SAM模型未加载';
            }
        } catch (e) {
            console.warn('Health check failed:', e);
            // Don't show error to user — might be network timing
        }
    }

    // =========================================================================
    // Initialization
    // =========================================================================
    function init() {
        cacheDOM();
        initTheme();
        initLazyLoading();
        initDragDrop();
        initTouchOptimizations();
        bindEvents();
        checkHealth();

        console.log('🌿 HerbiEstim Frontend v2.0.0 initialized');
        console.log('   Platform:', navigator.platform || 'unknown');
        console.log('   Touch support:', 'ontouchstart' in window ? 'yes' : 'no');
        console.log('   Theme:', state.theme);
    }

    // Run on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
