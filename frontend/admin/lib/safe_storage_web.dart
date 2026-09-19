import 'package:web/web.dart' as web;

String? webStorageGet(String key) {
  try {
    return web.window.localStorage.getItem('scanner_admin_$key');
  } catch (_) {
    return null;
  }
}

void webStorageSet(String key, String value) {
  try {
    web.window.localStorage.setItem('scanner_admin_$key', value);
  } catch (_) {}
}

void webStorageRemove(String key) {
  try {
    web.window.localStorage.removeItem('scanner_admin_$key');
  } catch (_) {}
}

void webStorageClear() {
  try {
    final storage = web.window.localStorage;
    final keysToRemove = <String>[];
    for (var i = 0; i < storage.length; i++) {
      final k = storage.key(i);
      if (k != null && k.startsWith('scanner_admin_')) {
        keysToRemove.add(k);
      }
    }
    for (final k in keysToRemove) {
      storage.removeItem(k);
    }
  } catch (_) {}
}
