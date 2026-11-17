// QR ссылки подписки с логотипом «VPN» по центру — одной картинкой (NPVPN-2368).
//
// qrcode.js рисует код на canvas, а потом асинхронно подменяет его на <img> и прячет canvas раньше,
// чем <img> отрисуется, — на эти кадры код пропадал. Логотип отдельным <img> поверх в это время был
// виден один. Поэтому код рисуем во временный контейнер, копируем в свой canvas вместе с логотипом
// и вставляем на страницу уже готовую картинку.
//
// Подключается после qrcode.min.js; вызывает страница: window.renderSubscriptionQr(target, url).
// Адрес логотипа — data-logo-src у target.
(function () {
  'use strict';

  var SIZE = 200; // на экране, см. components.css
  var SCALE = 2; // рисуем в 2× — чёткий код на ретине
  // Уровень коррекции H восстанавливает закрытый логотипом центр: 56 из 200 (~8% площади) —
  // с запасом, 60+ на плотном коде уже не всегда читается. Та же картинка, что в QR бота.
  var LOGO = 56;
  // Логотип необязателен: если он не загрузился за это время, показываем код без него,
  // а не пустое место
  var LOGO_WAIT_MS = 3000;

  function loadLogo(src) {
    if (!src) return Promise.resolve(null);
    var logo = new Image();
    logo.src = src;
    var loaded = logo.decode().then(
      function () { return logo; },
      function () { return null; }
    );
    var timeout = new Promise(function (resolve) {
      setTimeout(function () { resolve(null); }, LOGO_WAIT_MS);
    });
    return Promise.race([loaded, timeout]);
  }

  function hasCanvas() {
    var probe = document.createElement('canvas');
    return !!(probe.getContext && probe.getContext('2d'));
  }

  window.renderSubscriptionQr = function (target, text) {
    if (!target) return Promise.resolve();
    var options = { text: text, correctLevel: QRCode.CorrectLevel.H };

    if (!hasCanvas()) {
      // без canvas библиотека рисует таблицей — прямо в блок, чтобы размеры и отступы она считала
      // по нему; логотип на таблицу не наложить
      options.width = SIZE;
      options.height = SIZE;
      target.replaceChildren();
      new QRCode(target, options);
      return Promise.resolve();
    }

    var side = SIZE * SCALE;
    options.width = side;
    options.height = side;
    var draft = document.createElement('div');
    new QRCode(draft, options);
    // свой canvas, а не библиотечный: свой она позже прячет (display: none) при подмене на <img>
    var canvas = document.createElement('canvas');
    canvas.width = side;
    canvas.height = side;
    var ctx = canvas.getContext('2d');
    ctx.drawImage(draft.querySelector('canvas'), 0, 0);

    return loadLogo(target.getAttribute('data-logo-src')).then(function (logo) {
      if (logo) {
        var logoSide = LOGO * SCALE;
        var at = (side - logoSide) / 2;
        ctx.drawImage(logo, at, at, logoSide, logoSide);
      }
      // картинка уже на странице дальше не меняется: опоздавший логотип не дорисовываем
      target.replaceChildren(canvas);
    });
  };
})();
