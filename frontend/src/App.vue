<script setup>
import {onMounted,onUnmounted} from 'vue'
import {initRealtime} from './api.js'
import LoginOverlay from './components/LoginOverlay.vue'
import TrafficWorkbench from './components/TrafficWorkbench.vue'
let dispose
onMounted(()=>{dispose=initRealtime()})
onUnmounted(()=>dispose?.())
</script>
<template><LoginOverlay/><TrafficWorkbench/></template>
