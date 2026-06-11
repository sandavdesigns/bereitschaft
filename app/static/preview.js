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

    function normalizeTimeValue(value) {
      value = (value || '').trim();
      var match;
      var hour;
      var minute;
      if (!value) return value;
      if (/^\d{1,2}$/.test(value)) {
        hour = Number(value);
        if (hour >= 0 && hour <= 23) return value.padStart(2, '0') + ':00';
        return value;
      }
      match = value.match(/^(\d{1,2}):(\d{0,2})$/);
      if (match) {
        hour = Number(match[1]);
        minute = Number(match[2] || '0');
        if (hour >= 0 && hour <= 23 && minute >= 0 && minute <= 59) {
          return match[1].padStart(2, '0') + ':' + (match[2] || '00').padEnd(2, '0');
        }
      }
      return value;
    }

    function normalizeTimeField(field) {
      field.value = normalizeTimeValue(field.value);
    }

    document.querySelectorAll('[data-time-field]').forEach(function (field) {
      field.addEventListener('blur', function () {
        normalizeTimeField(field);
      });
    });

    document.addEventListener('submit', function (event) {
      event.target.querySelectorAll('[data-time-field]').forEach(normalizeTimeField);
    });

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
