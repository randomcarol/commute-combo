export function scheduleSearchProgress({
  onSlow,
  setTimeoutFn = setTimeout,
  clearTimeoutFn = clearTimeout,
  slowDelayMs = 5000,
}) {
  const slowTimerId = setTimeoutFn(() => {
    onSlow?.();
  }, slowDelayMs);

  return {
    cancel() {
      if (slowTimerId) {
        clearTimeoutFn(slowTimerId);
      }
    },
  };
}
