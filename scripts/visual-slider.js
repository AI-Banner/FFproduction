(() => {
  const track = document.getElementById('visual-track');
  if (!track) return;
  const previous = document.querySelector('.visual-prev');
  const next = document.querySelector('.visual-next');
  // Move the former final image into the second position.
  track.insertBefore(track.lastElementChild, track.children[1]);
  const originals = Array.from(track.children);
  const makeCopy = item => {
    const copy = item.cloneNode(true);
    copy.setAttribute('aria-hidden', 'true');
    copy.tabIndex = -1;
    copy.classList.add('is-visible');
    return copy;
  };
  track.prepend(...originals.map(makeCopy));
  track.append(...originals.map(makeCopy));
  const items = Array.from(track.children);
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const start = () => originals[0].offsetLeft - items[0].offsetLeft;
  const cycle = () => items[originals.length * 2].offsetLeft - originals[0].offsetLeft;
  let ready = false;
  let settleTimer;
  const normalize = () => {
    if (!ready || cycle() <= 0) return;
    const beginning = start();
    const length = cycle();
    let position = track.scrollLeft;
    while (position < beginning - 1) position += length;
    while (position >= beginning + length - 1) position -= length;
    if (Math.abs(position - track.scrollLeft) > 1) {
      track.scrollTo({ left: position, behavior: 'instant' });
    }
  };
  const move = direction => {
    normalize();
    const current = track.scrollLeft;
    const positions = items.map(item => item.offsetLeft - items[0].offsetLeft);
    const destination = direction > 0
      ? positions.find(position => position > current + 3)
      : positions.slice().reverse().find(position => position < current - 3);
    if (destination !== undefined) track.scrollTo({ left: destination, behavior: reducedMotion.matches ? 'instant' : 'smooth' });
  };
  previous.addEventListener('click', () => move(-1));
  next.addEventListener('click', () => move(1));
  track.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    event.preventDefault();
    move(event.key === 'ArrowRight' ? 1 : -1);
  });
  track.addEventListener('scroll', () => {
    clearTimeout(settleTimer);
    settleTimer = setTimeout(normalize, 180);
  }, { passive: true });
  track.addEventListener('scrollend', normalize);
  // Reserve intrinsic ratios before lazy images load, so the loop stays aligned.
  const sizes = [[1274,1600],[1920,2560],[1528,1920],[1076,1350],[1436,2560],[1920,2560],[1920,2560]];
  items.forEach((item, index) => {
    const image = item.querySelector('img');
    [image.width, image.height] = sizes[index % originals.length];
  });
  requestAnimationFrame(() => {
    track.scrollTo({ left: start(), behavior: 'instant' });
    ready = true;
  });
  new ResizeObserver(() => { if (ready) normalize(); }).observe(track);
  if ('IntersectionObserver' in window) {
    track.classList.add('is-enhanced');
    const observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: .15 });
    originals.forEach(item => observer.observe(item));
  }
})();
