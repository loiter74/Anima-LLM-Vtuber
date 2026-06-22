<template>
  <div class="flex items-center gap-1.5">
    <div class="flex items-center gap-[3px] px-[14px] py-2 bg-c-ai-bubble border border-c-border-accent rounded-xl rounded-bl-[6px] animate-fade-in shrink-0">
      <span v-for="i in 5" :key="i"
        class="w-[3px] bg-c-accent rounded-full"
        :style="{
          height: ['8px','14px','18px','14px','8px'][i - 1],
          animation: `speak-wave 0.9s ease-in-out infinite ${(i - 1) * 0.15}s`
        }"
      />
    </div>
    <span class="text-10px text-c-text-muted">语音中</span>
  </div>
</template>

<style scoped>
@keyframes speak-wave {
  0%, 100% { transform: scaleY(0.4); }
  50% { transform: scaleY(1.0); }
}
</style>
