<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { completeSignIn } from "../session";
const router = useRouter(); const failed = ref(false);
onMounted(async () => {
  try { const to = await completeSignIn(); await router.replace(to); } catch { failed.value = true; }
});
</script>
<template>
  <p v-if="!failed" role="status">…</p>
  <p v-else role="alert">Sign-in could not be completed. <a href="/">Try again</a></p>
</template>
