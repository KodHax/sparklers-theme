/**
 * Bundle quantity enforcement for Sparklers Portugal.
 * Parses product titles to extract minimum bundle quantities (e.g. "90 Uni.")
 * and enforces them on product pages and cart (drawer + /cart page).
 */

function getMinQtyFromTitle(title) {
  if (!title) return null;
  const match = title.match(/(\d+)\s*Uni\.?/i);
  if (match) {
    const qty = parseInt(match[1], 10);
    if (qty > 1) return qty;
  }
  const packMatch = title.match(/pack\s*(?:de\s*)?(\d+)/i);
  if (packMatch) {
    const qty = parseInt(packMatch[1], 10);
    if (qty > 1) return qty;
  }
  return null;
}

function enforceBundleOnProductPage() {
  const form = document.querySelector('form[action*="/cart/add"]');
  if (!form) return;

  const titleEl = document.querySelector('h1');
  if (!titleEl) return;

  const minQty = getMinQtyFromTitle(titleEl.textContent);
  if (!minQty) return;

  const quantityInput = form.querySelector('input[name="quantity"]');
  if (!quantityInput) return;

  const currentMin = parseInt(quantityInput.min, 10) || 1;
  if (minQty > currentMin) {
    quantityInput.min = minQty;
    quantityInput.setAttribute('data-min', minQty);
    if (parseInt(quantityInput.value, 10) < minQty) {
      quantityInput.value = minQty;
    }
  }

  const wrapper = quantityInput.closest('.quantity-selector-wrapper') ||
                  quantityInput.closest('quantity-selector-component')?.parentElement;
  if (wrapper && !wrapper.querySelector('.bundle-min-notice')) {
    const notice = document.createElement('div');
    notice.className = 'bundle-min-notice';
    notice.innerHTML = `
      <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
      <span>Quantidade mínima: ${minQty} unidades</span>
    `;
    wrapper.after(notice);
  }

  const qtyComponent = quantityInput.closest('quantity-selector-component');
  if (qtyComponent) {
    const minusBtn = qtyComponent.querySelector('button[name="minus"]');
    if (minusBtn) {
      const checkMinus = () => {
        minusBtn.disabled = parseInt(quantityInput.value, 10) <= minQty;
      };
      quantityInput.addEventListener('change', checkMinus);
      new MutationObserver(checkMinus).observe(quantityInput, { attributes: true, attributeFilter: ['value'] });
      checkMinus();
    }
  }

  quantityInput.addEventListener('change', () => {
    if (parseInt(quantityInput.value, 10) < minQty) {
      quantityInput.value = minQty;
    }
  });

  quantityInput.addEventListener('blur', () => {
    if (parseInt(quantityInput.value, 10) < minQty) {
      quantityInput.value = minQty;
    }
  });
}

function enforceBundleOnCart() {
  const cartItems = document.querySelectorAll('[data-cart-line]');
  cartItems.forEach((input) => {
    const row = input.closest('tr, li, .cart-item, [class*="cart"]');
    if (!row) return;

    const titleEl = row.querySelector('a[href*="/products/"]') || row.querySelector('[class*="title"]');
    if (!titleEl) return;

    const minQty = getMinQtyFromTitle(titleEl.textContent);
    if (!minQty) return;

    const currentMin = parseInt(input.min, 10) || 1;
    if (minQty > currentMin) {
      input.min = minQty;
      if (parseInt(input.value, 10) < minQty) {
        input.value = minQty;
      }
    }

    input.addEventListener('change', () => {
      if (parseInt(input.value, 10) < minQty) {
        input.value = minQty;
        input.dispatchEvent(new Event('change', { bubbles: true }));
      }
    });

    input.addEventListener('blur', () => {
      if (parseInt(input.value, 10) < minQty) {
        input.value = minQty;
      }
    });

    const qtyComponent = input.closest('cart-quantity-selector-component');
    if (qtyComponent) {
      const minusBtn = qtyComponent.querySelector('button[name="minus"]');
      if (minusBtn) {
        const checkMinus = () => {
          minusBtn.disabled = parseInt(input.value, 10) <= minQty;
        };
        input.addEventListener('change', checkMinus);
        new MutationObserver(checkMinus).observe(input, { attributes: true, attributeFilter: ['value'] });
        checkMinus();
      }
    }
  });
}

function init() {
  enforceBundleOnProductPage();
  enforceBundleOnCart();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}

document.addEventListener('cart:updated', () => {
  setTimeout(enforceBundleOnCart, 300);
});

const observer = new MutationObserver((mutations) => {
  for (const mutation of mutations) {
    if (mutation.addedNodes.length) {
      const hasCartContent = Array.from(mutation.addedNodes).some(
        (node) => node.nodeType === 1 && (
          node.querySelector?.('[data-cart-line]') ||
          node.matches?.('[data-cart-line]')
        )
      );
      if (hasCartContent) {
        setTimeout(enforceBundleOnCart, 100);
      }
    }
  }
});
observer.observe(document.body, { childList: true, subtree: true });
