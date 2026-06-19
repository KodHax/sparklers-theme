/**
 * Product page conversion enhancements for Sparklers Portugal.
 * - Sticky add-to-cart bar on scroll
 * - "Encomenda até Xh, envio hoje" urgency
 */

(function productEnhancements() {
  if (document.querySelector('.product-information-section') === null &&
      document.querySelector('[data-section-type="product-information"]') === null &&
      !document.querySelector('product-information-component')) {
    const isProductPage = document.querySelector('form[action*="/cart/add"]') &&
                          document.querySelector('h1');
    if (!isProductPage) return;
  }

  createStickyBar();
  enhanceQuantitySelector();
  createUrgencyMessage();
})();

function createStickyBar() {
  const form = document.querySelector('form[action*="/cart/add"]');
  if (!form) return;

  const addToCartBtn = form.querySelector('button[type="submit"], [name="add"]');
  if (!addToCartBtn) return;

  const bar = document.createElement('div');
  bar.className = 'sticky-atc-bar';
  bar.innerHTML = `
    <div class="sticky-atc-bar__inner">
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
    const titleSpan = bar.querySelector('.sticky-atc-bar__title');
    titleSpan.textContent = titleEl.textContent.trim();
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

  let lastScroll = 0;
  const observer = new IntersectionObserver(
    ([entry]) => {
      bar.classList.toggle('sticky-atc-bar--visible', !entry.isIntersecting && window.scrollY > 200);
    },
    { threshold: 0 }
  );

  if (addToCartBtn) observer.observe(addToCartBtn);
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

    input.addEventListener('focus', () => {
      wrapper.style.borderColor = '#E8A0B4';
    });
    input.addEventListener('blur', () => {
      wrapper.style.borderColor = '#e8e4e0';
    });
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

  buyButtonsWrapper.after(urgency);
}
