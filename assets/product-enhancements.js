/**
 * Product page conversion enhancements for Sparklers Portugal.
 * Inspired by high-converting DTC stores, adapted for wedding/celebration niche.
 */

(function productEnhancements() {
  if (document.querySelector('.product-information-section') === null &&
      document.querySelector('[data-section-type="product-information"]') === null &&
      !document.querySelector('product-information-component')) {
    const isProductPage = document.querySelector('form[action*="/cart/add"]') &&
                          document.querySelector('h1');
    if (!isProductPage) return;
  }

  createSavingsBadge();
  createUSPBullets();
  enhanceQuantitySelector();
  createPaymentIcons();
  createShippingEstimate();
  createUrgencyMessage();
  createViewerCount();
  createStickyBar();
})();

function createSavingsBadge() {
  const regularPrice = document.querySelector('.price-item--regular');
  const salePrice = document.querySelector('.price-item--sale');
  if (!regularPrice || !salePrice) return;

  const parsePrice = (el) => {
    const text = el.textContent.replace(/[^\d,.]/g, '').replace(',', '.');
    return parseFloat(text);
  };

  const reg = parsePrice(regularPrice);
  const sale = parsePrice(salePrice);
  if (isNaN(reg) || isNaN(sale) || reg <= sale) return;

  const savings = (reg - sale).toFixed(2).replace('.', ',');
  const badge = document.createElement('span');
  badge.className = 'savings-badge';
  badge.innerHTML = `🏷️ Poupa €${savings}`;

  const priceWrapper = salePrice.closest('.price') || salePrice.parentElement;
  if (priceWrapper) {
    priceWrapper.style.display = 'flex';
    priceWrapper.style.alignItems = 'center';
    priceWrapper.style.flexWrap = 'wrap';
    priceWrapper.style.gap = '8px';
    priceWrapper.appendChild(badge);
  }
}

function createUSPBullets() {
  const form = document.querySelector('form[action*="/cart/add"]');
  if (!form) return;

  const priceBlock = document.querySelector('.price')?.closest('[class*="block"]') ||
                     document.querySelector('.price')?.parentElement?.parentElement;
  if (!priceBlock) return;

  const usp = document.createElement('div');
  usp.className = 'product-usp-bullets';
  usp.innerHTML = `
    <div class="product-usp-bullet">
      <span class="product-usp-icon">🚚</span>
      <span>Envio em <strong>24h úteis</strong></span>
    </div>
    <div class="product-usp-bullet">
      <span class="product-usp-icon">✅</span>
      <span>Certificação <strong>CE</strong> — Seguro para eventos</span>
    </div>
    <div class="product-usp-bullet">
      <span class="product-usp-icon">🔒</span>
      <span>Pagamento <strong>seguro</strong> — MB Way, Multibanco, Cartão</span>
    </div>
    <div class="product-usp-bullet">
      <span class="product-usp-icon">↩️</span>
      <span>Devoluções <strong>14 dias</strong></span>
    </div>
  `;

  const variantPicker = form.closest('[class*="product-details"]')?.querySelector('[class*="variant"]') ||
                        document.querySelector('variant-picker') ||
                        document.querySelector('[class*="variant-picker"]');

  if (variantPicker) {
    variantPicker.before(usp);
  } else {
    const buySection = form.closest('[class*="buy-button"]') || form.parentElement;
    if (buySection) buySection.before(usp);
  }
}

function createPaymentIcons() {
  const form = document.querySelector('form[action*="/cart/add"]');
  if (!form) return;

  const buyButtonsWrapper = form.closest('[class*="buy-button"]') ||
                            form.closest('.buy-buttons') ||
                            form.parentElement;
  if (!buyButtonsWrapper) return;

  const payments = document.createElement('div');
  payments.className = 'payment-methods';
  payments.innerHTML = `
    <div class="payment-methods__icons">
      <span class="payment-icon" title="MB Way">
        <svg width="32" height="20" viewBox="0 0 32 20" fill="none"><rect width="32" height="20" rx="3" fill="#fff" stroke="#ddd"/><text x="16" y="13" text-anchor="middle" font-size="7" font-weight="700" fill="#E21A23">MB</text></svg>
      </span>
      <span class="payment-icon" title="Visa">
        <svg width="32" height="20" viewBox="0 0 32 20" fill="none"><rect width="32" height="20" rx="3" fill="#fff" stroke="#ddd"/><text x="16" y="14" text-anchor="middle" font-size="8" font-weight="700" font-style="italic" fill="#1A1F71">VISA</text></svg>
      </span>
      <span class="payment-icon" title="Mastercard">
        <svg width="32" height="20" viewBox="0 0 32 20" fill="none"><rect width="32" height="20" rx="3" fill="#fff" stroke="#ddd"/><circle cx="13" cy="10" r="5" fill="#EB001B" opacity="0.8"/><circle cx="19" cy="10" r="5" fill="#F79E1B" opacity="0.8"/></svg>
      </span>
      <span class="payment-icon" title="PayPal">
        <svg width="32" height="20" viewBox="0 0 32 20" fill="none"><rect width="32" height="20" rx="3" fill="#fff" stroke="#ddd"/><text x="16" y="13" text-anchor="middle" font-size="7" font-weight="700" fill="#003087">Pay</text></svg>
      </span>
      <span class="payment-icon" title="Apple Pay">
        <svg width="32" height="20" viewBox="0 0 32 20" fill="none"><rect width="32" height="20" rx="3" fill="#000"/><text x="16" y="13" text-anchor="middle" font-size="7" font-weight="500" fill="#fff">Pay</text></svg>
      </span>
    </div>
    <span class="payment-methods__label">Encriptação SSL em todas as transações</span>
  `;

  const existingUrgency = buyButtonsWrapper.parentElement?.querySelector('.urgency-message');
  if (existingUrgency) {
    existingUrgency.after(payments);
  } else {
    buyButtonsWrapper.after(payments);
  }
}

function createShippingEstimate() {
  const form = document.querySelector('form[action*="/cart/add"]');
  if (!form) return;

  const buyButtonsWrapper = form.closest('[class*="buy-button"]') ||
                            form.closest('.buy-buttons') ||
                            form.parentElement;
  if (!buyButtonsWrapper) return;

  const now = new Date();
  const hour = now.getHours();
  const day = now.getDay();

  let shipDate = new Date(now);

  if (day === 0) {
    shipDate.setDate(shipDate.getDate() + 1);
  } else if (day === 6) {
    shipDate.setDate(shipDate.getDate() + 2);
  } else if (hour >= 14) {
    shipDate.setDate(shipDate.getDate() + 1);
    if (shipDate.getDay() === 0) shipDate.setDate(shipDate.getDate() + 1);
    if (shipDate.getDay() === 6) shipDate.setDate(shipDate.getDate() + 2);
  }

  const weekdays = ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb'];
  const dayName = weekdays[shipDate.getDay()];
  const dd = String(shipDate.getDate()).padStart(2, '0');
  const mm = String(shipDate.getMonth() + 1).padStart(2, '0');

  const estimate = document.createElement('div');
  estimate.className = 'shipping-estimate';
  estimate.innerHTML = `
    <span class="shipping-estimate__dot"></span>
    <span>Enviado <strong>${dayName}. ${dd}/${mm}</strong></span>
    <span class="shipping-estimate__flag">PT</span>
    <span><strong>ENVIOS EM 24H</strong></span>
  `;

  buyButtonsWrapper.after(estimate);
}

function enhanceQuantitySelector() {
  const qtyInputs = document.querySelectorAll('quantity-input, .quantity-selector');
  qtyInputs.forEach(wrapper => {
    const input = wrapper.querySelector('input[type="number"]');
    if (!input) return;

    const buttons = wrapper.querySelectorAll('button');
    if (buttons.length >= 2) {
      buttons.forEach(btn => {
        btn.setAttribute('aria-label', btn.textContent.trim() === '+' ? 'Aumentar quantidade' : 'Diminuir quantidade');
      });
    }

    input.addEventListener('focus', () => { wrapper.style.borderColor = '#E8A0B4'; });
    input.addEventListener('blur', () => { wrapper.style.borderColor = '#e8e4e0'; });
  });
}

function createUrgencyMessage() {
  const form = document.querySelector('form[action*="/cart/add"]');
  if (!form) return;

  const now = new Date();
  const hour = now.getHours();
  const day = now.getDay();

  if (day === 0 || day === 6) return;

  const buyButtonsWrapper = form.closest('[class*="buy-button"]') ||
                            form.closest('.buy-buttons') ||
                            form.parentElement;
  if (!buyButtonsWrapper) return;

  let message = '';
  if (hour < 14) {
    message = `Encomende nas próximas <strong>${14 - hour}h</strong> para envio hoje`;
  } else {
    message = 'Encomende agora para envio amanhã às 9h';
  }

  const urgency = document.createElement('div');
  urgency.className = 'urgency-message';
  urgency.innerHTML = `
    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
    <span>${message}</span>
  `;

  const shippingEst = buyButtonsWrapper.parentElement?.querySelector('.shipping-estimate');
  if (shippingEst) {
    shippingEst.after(urgency);
  } else {
    buyButtonsWrapper.after(urgency);
  }
}

function createViewerCount() {
  const form = document.querySelector('form[action*="/cart/add"]');
  if (!form) return;

  const buyButtonsWrapper = form.closest('[class*="buy-button"]') ||
                            form.closest('.buy-buttons') ||
                            form.parentElement;
  if (!buyButtonsWrapper) return;

  const baseCount = 3 + Math.floor(Math.random() * 8);

  const viewer = document.createElement('div');
  viewer.className = 'viewer-count';
  viewer.innerHTML = `
    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
    <span><strong>${baseCount}</strong> pessoas estão a ver este produto</span>
  `;

  const urgencyEl = buyButtonsWrapper.parentElement?.querySelector('.urgency-message');
  const paymentEl = buyButtonsWrapper.parentElement?.querySelector('.payment-methods');
  const insertAfter = paymentEl || urgencyEl || buyButtonsWrapper;
  insertAfter.after(viewer);

  setInterval(() => {
    const delta = Math.random() > 0.5 ? 1 : -1;
    const current = parseInt(viewer.querySelector('strong').textContent);
    const newCount = Math.max(2, Math.min(15, current + delta));
    viewer.querySelector('strong').textContent = newCount;
  }, 8000 + Math.random() * 7000);
}

function createStickyBar() {
  const form = document.querySelector('form[action*="/cart/add"]');
  if (!form) return;

  const addToCartBtn = form.querySelector('button[type="submit"], [name="add"]');
  if (!addToCartBtn) return;

  const productImg = document.querySelector('.product-media img, [class*="product-media"] img, [class*="media-gallery"] img');
  const imgSrc = productImg ? (productImg.src || productImg.currentSrc) : '';

  const bar = document.createElement('div');
  bar.className = 'sticky-atc-bar';
  bar.innerHTML = `
    <div class="sticky-atc-bar__inner">
      ${imgSrc ? `<img class="sticky-atc-bar__img" src="${imgSrc}" alt="" width="44" height="44">` : ''}
      <div class="sticky-atc-bar__info">
        <span class="sticky-atc-bar__title"></span>
        <span class="sticky-atc-bar__price"></span>
      </div>
      <button type="button" class="sticky-atc-bar__button">
        Adicionar ao carrinho
      </button>
    </div>
  `;
  document.body.appendChild(bar);

  const titleEl = document.querySelector('h1');
  if (titleEl) {
    bar.querySelector('.sticky-atc-bar__title').textContent = titleEl.textContent.trim();
  }

  function updatePrice() {
    const priceEl = document.querySelector('.price-item--sale, .price-item--regular, [data-product-price]');
    if (priceEl) {
      bar.querySelector('.sticky-atc-bar__price').textContent = priceEl.textContent.trim();
    }
  }
  updatePrice();

  const priceContainer = document.querySelector('.price, [data-product-price-wrapper]');
  if (priceContainer) {
    new MutationObserver(updatePrice).observe(priceContainer, { childList: true, subtree: true, characterData: true });
  }

  bar.querySelector('.sticky-atc-bar__button').addEventListener('click', () => {
    addToCartBtn.click();
  });

  const observer = new IntersectionObserver(
    ([entry]) => {
      bar.classList.toggle('sticky-atc-bar--visible', !entry.isIntersecting && window.scrollY > 200);
    },
    { threshold: 0 }
  );

  if (addToCartBtn) observer.observe(addToCartBtn);
}
