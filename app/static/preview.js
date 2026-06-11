(function () {
  function ready(callback) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', callback);
    } else {
      callback();
    }
  }

  ready(function () {
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
  });
}());
