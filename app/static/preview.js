(function () {
  function ready(callback) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', callback);
    } else {
      callback();
    }
  }

  ready(function () {
    window.__bereitschaftPreviewLoaded = true;

    var previewModal = document.getElementById('preview-modal');
    var previewFrame = document.getElementById('preview-frame');
    var previewTitle = document.getElementById('preview-title');
    var previewClose = document.getElementById('preview-close');
    var previewPrint = document.getElementById('preview-print');

    if (!previewModal || !previewFrame || !previewTitle || !previewClose || !previewPrint) {
      return;
    }

    function openPreview(url, title) {
      previewTitle.textContent = title || 'Vorschau';
      previewFrame.src = url;
      previewModal.classList.add('open');
      previewModal.setAttribute('aria-hidden', 'false');
    }

    function closePreview() {
      previewModal.classList.remove('open');
      previewModal.setAttribute('aria-hidden', 'true');
      previewFrame.src = 'about:blank';
    }

    document.addEventListener('click', function (event) {
      var trigger = event.target.closest('[data-preview-url]');
      if (!trigger) return;
      event.preventDefault();
      openPreview(trigger.getAttribute('data-preview-url'), trigger.getAttribute('data-preview-title'));
    });

    previewClose.addEventListener('click', closePreview);
    previewModal.addEventListener('click', function (event) {
      if (event.target === previewModal) closePreview();
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && previewModal.classList.contains('open')) closePreview();
    });
    previewPrint.addEventListener('click', function () {
      if (previewFrame.contentWindow) previewFrame.contentWindow.print();
    });
  });
}());
