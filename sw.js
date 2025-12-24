// Service Worker for Ara Voice PWA
const CACHE_NAME = 'ara-voice-v1';
const urlsToCache = [
    '/ara.html',
    '/manifest.json'
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => cache.addAll(urlsToCache))
    );
});

self.addEventListener('fetch', (event) => {
    // Network first, fallback to cache
    event.respondWith(
        fetch(event.request)
            .catch(() => caches.match(event.request))
    );
});
