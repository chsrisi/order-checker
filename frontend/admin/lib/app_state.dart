import 'dart:async';
import 'dart:convert';
import 'dart:developer';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:web_socket_channel/io.dart';
import 'package:http/http.dart' as http;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:path_provider/path_provider.dart';
import 'package:open_file/open_file.dart';
import 'package:jose/jose.dart';
import 'models.dart';

enum AdminView {
  users(true),
  finder(true),
  orders(true),
  stocks(true),
  account(false);

  final bool isMainView;

  const AdminView(this.isMainView);
}

class SecurityService {
  static const _storage = FlutterSecureStorage();

  static const String jwksCacheKey = 'jwks_cache';
  static const String jwksTimestampKey = 'jwks_timestamp';
  static const int jwksTtlMs = 12 * 60 * 60 * 1000; // 12 hours

  static String? _baseUrl;

  static void init(String baseUrl) {
    _baseUrl = baseUrl;
  }

  // 1. Fetching & Caching JWKS
  static Future<JsonWebKeySet> getJwks({bool forceRefresh = false}) async {
    if (_baseUrl == null) {
      throw Exception("SecurityService not initialized with baseUrl");
    }

    if (!forceRefresh) {
      final cachedJwks = await _storage.read(key: jwksCacheKey);
      final cachedTimeStr = await _storage.read(key: jwksTimestampKey);

      if (cachedJwks != null && cachedTimeStr != null) {
        final cachedTime = int.tryParse(cachedTimeStr) ?? 0;
        final now = DateTime.now().millisecondsSinceEpoch;

        if (now - cachedTime < jwksTtlMs) {
          try {
            return JsonWebKeySet.fromJson(jsonDecode(cachedJwks));
          } catch (e) {
            // Log parse fail, fallback to fetch
          }
        }
      }
    }

    // Fetch from server
    final uri = Uri.parse('$_baseUrl/.well-known/jwks.json');
    final response = await http.get(uri).timeout(const Duration(seconds: 10));

    if (response.statusCode == 200) {
      final jwksJson = response.body;
      await _storage.write(key: jwksCacheKey, value: jwksJson);
      await _storage.write(
        key: jwksTimestampKey,
        value: DateTime.now().millisecondsSinceEpoch.toString(),
      );

      return JsonWebKeySet.fromJson(jsonDecode(jwksJson));
    } else {
      throw Exception('Failed to fetch JWKS from server');
    }
  }

  // 2. Clear Cache
  static Future<void> clearJwksCache() async {
    await _storage.delete(key: jwksCacheKey);
    await _storage.delete(key: jwksTimestampKey);
  }

  // 3. Validate JWT
  static Future<bool> isTokenValid(String token) async {
    try {
      final jws = JsonWebSignature.fromCompactSerialization(token);
      var jwks = await getJwks();
      var keyStore = JsonWebKeyStore()..addKeySet(jwks);

      // Attempt verification
      var isValid = await jws.verify(keyStore);

      // If validation fails, force refresh JWKS in case of rotation
      if (!isValid) {
        await clearJwksCache();
        jwks = await getJwks(forceRefresh: true);
        keyStore = JsonWebKeyStore()..addKeySet(jwks);
        isValid = await jws.verify(keyStore);
      }

      if (!isValid) return false;

      // Check expiration manually
      final payload = jws.unverifiedPayload.jsonContent;
      if (payload.containsKey('exp')) {
        final exp = payload['exp'] as int;
        final now = DateTime.now().millisecondsSinceEpoch ~/ 1000;
        if (now >= exp) return false;
      }

      return true;
    } catch (e) {
      return false; // Malformed token
    }
  }
}

class AppState extends ChangeNotifier {
  List<OutboundItem> _scannedItems = [];
  List<AdminUser> _registeredUsers = [];
  List<WarehouseItem> _foundItems = [];
  List<ShopeeOrder> _orders = [];
  List<PickItemEntry> _pickItemEntries = [];
  List<Stock> _stocks = [];

  List<OutboundItem> _historyOutboundItems = [];
  List<ShopeeOrder> _historyOrders = [];

  int _lastCloseOutbound = 0;
  int _lastCloseUnknown = 0;
  int _lastCloseOrdersDone = 0;

  bool _isLoading = false;
  bool _isGlobalLoading = false;

  bool _isLoggedIn = false;
  String _username = '';
  AdminView _currentView = AdminView.orders;

  final _storage = const FlutterSecureStorage();
  final String _baseUrl = dotenv.env['BASE_URL'] ?? '';
  final String _wsUrl = dotenv.env['WS_URL'] ?? '';

  WebSocketChannel? _channel;
  StreamSubscription? _wsSubscription;
  int _wsRetryCount = 0;
  bool _wsConnectionFailed = false;

  Completer<String?>? _refreshTokenCompleter;

  // Getters
  List<OutboundItem> get scannedItems => _scannedItems;
  List<AdminUser> get registeredUsers => _registeredUsers;
  List<WarehouseItem> get foundItems => _foundItems;
  List<ShopeeOrder> get orders => _orders;
  List<PickItemEntry> get pickItemEntries => _pickItemEntries;
  List<Stock> get stocks => _stocks;
  List<OutboundItem> get historyOutboundItems => _historyOutboundItems;
  List<ShopeeOrder> get historyOrders => _historyOrders;
  int get lastCloseOutbound => _lastCloseOutbound;
  int get lastCloseUnknown => _lastCloseUnknown;
  int get lastCloseOrdersDone => _lastCloseOrdersDone;
  bool get isLoading => _isLoading;
  bool get isGlobalLoading => _isGlobalLoading;
  bool get isLoggedIn => _isLoggedIn;
  String get username => _username;
  AdminView get currentView => _currentView;
  bool get wsConnectionFailed => _wsConnectionFailed;
  String get baseUrl => _baseUrl;

  void initialize() {
    SecurityService.init(_baseUrl);
    checkLoginStatus();
  }

  @override
  void dispose() {
    _closeWebSocket();
    super.dispose();
  }

  void _closeWebSocket() {
    _wsSubscription?.cancel();
    _channel?.sink.close();
    _channel = null;
  }

  Future<void> initWebSocket() async {
    if (_channel != null) return;

    final token = await _storage.read(key: 'access_token');
    if (token == null) return;

    try {
      final uri = Uri.parse('$_wsUrl/ws?token=$token');
      _channel = IOWebSocketChannel.connect(uri);

      _wsSubscription = _channel!.stream.listen(
        (message) {
          if (_wsRetryCount > 0 || _wsConnectionFailed) {
            _wsRetryCount = 0;
            _wsConnectionFailed = false;
            notifyListeners();
          }

          final data = jsonDecode(message);
          final type = data['type'];
          final payload = List<Map<String, dynamic>>.from(data['data']);

          if (type == 'outbound_update') {
            _scannedItems = payload
                .map((i) => OutboundItem.fromJson(i))
                .toList();
          } else if (type == 'users_update') {
            _registeredUsers = payload
                .map((i) => AdminUser.fromJson(i))
                .toList();
          } else if (type == 'shopee_orders_update') {
            _orders = payload.map((i) => ShopeeOrder.fromJson(i)).toList();
          } else if (type == 'pick_item_entries_update') {
            _pickItemEntries = payload
                .map((i) => PickItemEntry.fromJson(i))
                .toList();
          } else if (type == 'stocks_update') {
            _stocks = payload.map((i) => Stock.fromJson(i)).toList();
          }
          _isLoading = false;
          notifyListeners();
        },
        onError: (error) {
          log("WebSocket Error: $error");
          _reconnectWebSocket(error: error);
        },
        onDone: () {
          log("WebSocket Done");
          _reconnectWebSocket();
        },
      );
    } catch (e) {
      log("WebSocket Init Error: $e");
      _reconnectWebSocket(error: e);
    }
  }

  void _reconnectWebSocket({dynamic error}) async {
    _closeWebSocket();

    if (error != null && error.toString().contains('403')) {
      log("WebSocket Admin: 403 detected, attempting token refresh...");
      final newToken = await performRefresh();
      if (newToken != null) {
        log("WebSocket Admin: Token refreshed, re-initializing...");
        initWebSocket();
        return;
      }
    }

    _wsRetryCount++;
    if (_wsRetryCount > 5) {
      log("WebSocket Admin: max retries exceeded, stopping.");
      _wsConnectionFailed = true;
      _isLoading = false;
      notifyListeners();
      return;
    }

    log("WebSocket Admin: retry attempt $_wsRetryCount/5");
    Future.delayed(const Duration(seconds: 2), () {
      if (_isLoggedIn) {
        initWebSocket();
      }
    });
    notifyListeners();
  }

  void retryWebSocket() {
    _wsRetryCount = 0;
    _wsConnectionFailed = false;
    initWebSocket();
    notifyListeners();
  }

  Future<void> checkLoginStatus() async {
    final accessToken = await _storage.read(key: 'access_token');
    if (accessToken == null) return;

    _username = await _storage.read(key: 'username') ?? '';

    if (!await SecurityService.isTokenValid(accessToken)) {
      final newToken = await performRefresh();
      if (newToken != null) {
        _isLoggedIn = true;
        initWebSocket();
        loadCurrentViewData();
      }
    } else {
      _isLoggedIn = true;
      initWebSocket();
      loadCurrentViewData();
    }
    notifyListeners();
  }

  Future<String?> performRefresh() async {
    if (_refreshTokenCompleter != null) {
      return await _refreshTokenCompleter!.future;
    }

    _refreshTokenCompleter = Completer<String?>();
    try {
      final refreshToken = await _storage.read(key: 'refresh_token');
      if (refreshToken == null) {
        handleLogout(sessionExpired: false);
        _refreshTokenCompleter!.complete(null);
        return null;
      }

      final refreshResp = await makeRequest(
        '$_baseUrl/auth/refresh',
        method: 'POST',
        body: {'refresh_token': refreshToken},
        requiresAuth: false,
      );

      if (refreshResp?.statusCode == 200) {
        final data = jsonDecode(refreshResp!.body);
        await _storage.write(key: 'access_token', value: data['access_token']);
        await _storage.write(
          key: 'refresh_token',
          value: data['refresh_token'],
        );

        final newToken = data['access_token'];
        _refreshTokenCompleter!.complete(newToken);
        return newToken;
      } else {
        await handleLogout(sessionExpired: true);
        _refreshTokenCompleter!.complete(null);
        return null;
      }
    } catch (e) {
      _refreshTokenCompleter!.complete(null);
      return null;
    } finally {
      _refreshTokenCompleter = null;
    }
  }

  void loadCurrentViewData() {
    if (_currentView == AdminView.users) {
      fetchUsers();
    } else if (_currentView == AdminView.orders) {
      fetchAdminLabels();
      fetchHistory();
    } else if (_currentView == AdminView.stocks) {
      fetchStocks();
    }
  }

  void setView(AdminView view) {
    _currentView = view;
    loadCurrentViewData();
    notifyListeners();
  }

  Future<http.Response?> makeRequest(
    String url, {
    String method = 'GET',
    dynamic body,
    bool requiresAuth = true,
  }) async {
    _isGlobalLoading = true;
    notifyListeners();
    try {
      Future<http.Response> doRequest(String? token) async {
        final uri = Uri.parse(url);
        final payload = body != null ? jsonEncode(body) : null;

        final headers = <String, String>{"Content-Type": "application/json"};

        if (requiresAuth && token != null) {
          headers['Authorization'] = 'Bearer $token';
        }

        http.Response response;

        if (method == 'POST') {
          response = await http.post(uri, headers: headers, body: payload);
        } else if (method == 'DELETE') {
          response = await http.delete(uri, headers: headers, body: payload);
        } else {
          response = await http.get(uri, headers: headers);
        }

        return response;
      }

      String? accessToken = requiresAuth
          ? await _storage.read(key: 'access_token')
          : null;
      if (requiresAuth && accessToken == null) return null;

      var response = await doRequest(
        accessToken,
      ).timeout(const Duration(seconds: 15));

      if (requiresAuth && response.statusCode == 401) {
        final newToken = await performRefresh();
        if (newToken != null) {
          return await doRequest(newToken).timeout(const Duration(seconds: 15));
        } else {
          return response;
        }
      }
      return response;
    } catch (e) {
      log("Request Error: $e");
      return null;
    } finally {
      _isGlobalLoading = false;
      notifyListeners();
    }
  }

  Future<void> handleLogout({bool sessionExpired = false}) async {
    final refreshToken = await _storage.read(key: 'refresh_token');
    if (refreshToken != null) {
      await makeRequest(
        '$_baseUrl/auth/logout',
        method: 'POST',
        body: {'refresh_token': refreshToken},
        requiresAuth: false,
      );
    }
    await _storage.deleteAll();
    _isLoggedIn = false;
    _username = '';
    _scannedItems = [];
    _registeredUsers = [];
    _foundItems = [];
    _orders = [];
    _pickItemEntries = [];
    _stocks = [];
    _closeWebSocket();
    notifyListeners();
  }

  Future<bool> login(String username, String password) async {
    if (username.isEmpty || password.isEmpty) return false;

    _isLoading = true;
    notifyListeners();

    try {
      final response = await makeRequest(
        '$_baseUrl/auth/admin',
        method: 'POST',
        body: {'username': username, 'password': password},
        requiresAuth: false,
      );

      if (response?.statusCode == 200) {
        final data = jsonDecode(response!.body);
        await _storage.write(key: 'access_token', value: data['access_token']);
        await _storage.write(
          key: 'refresh_token',
          value: data['refresh_token'],
        );
        await _storage.write(key: 'username', value: username);

        _isLoggedIn = true;
        _username = username;
        initWebSocket();
        loadCurrentViewData();
        notifyListeners();
        return true;
      }
      return false;
    } catch (e) {
      log("Login Error: $e");
      return false;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> fetchHistory() async {
    _isLoading = true;
    notifyListeners();
    if (_channel == null) await initWebSocket();
    _channel?.sink.add(jsonEncode({'command': 'get_items'}));
  }

  Future<void> fetchAdminLabels() async {
    _isLoading = true;
    notifyListeners();
    if (_channel == null) await initWebSocket();
    _channel?.sink.add(jsonEncode({'command': 'get_shopee_orders'}));
  }

  Future<void> fetchShopeeOrders() async {
    _isLoading = true;
    notifyListeners();
    try {
      final response = await makeRequest(
        '$_baseUrl/shopee/orders',
        method: 'GET',
      );
      if (response?.statusCode != 200) {
        log("Failed to fetch Shopee orders. Status: ${response?.statusCode}");
      }
    } catch (e) {
      log("Fetch Shopee Orders Error: $e");
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> fetchAdminHistory() async {
    _isLoading = true;
    notifyListeners();
    try {
      final resOutbound = await makeRequest('$_baseUrl/admin/history/outbound');
      if (resOutbound?.statusCode == 200) {
        _historyOutboundItems = (jsonDecode(resOutbound!.body) as List)
            .map((i) => OutboundItem.fromJson(i))
            .toList();
      }
      final resOrders = await makeRequest(
        '$_baseUrl/admin/history/shopee/orders',
      );
      if (resOrders?.statusCode == 200) {
        _historyOrders = (jsonDecode(resOrders!.body) as List)
            .map((i) => ShopeeOrder.fromJson(i))
            .toList();
      }
    } catch (e) {
      log("Fetch Admin History Error: $e");
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<bool> markLabelDone(int labelId, bool done) async {
    _isLoading = true;
    notifyListeners();
    try {
      final response = await makeRequest(
        '$_baseUrl/labels/done?label_id=$labelId&done=$done',
        method: 'POST',
      );
      if (response?.statusCode == 200) {
        fetchAdminLabels();
        return true;
      }
      return false;
    } catch (e) {
      log("Mark Done Error: $e");
      return false;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> fetchUsers() async {
    _isLoading = true;
    notifyListeners();
    if (_channel == null) await initWebSocket();
    _channel?.sink.add(jsonEncode({'command': 'get_users'}));
  }

  Future<void> searchItems(String query) async {
    if (query.isEmpty) return;

    _isLoading = true;
    notifyListeners();
    try {
      final response = await makeRequest('$_baseUrl/items/find?query=$query');
      if (response?.statusCode == 200) {
        _foundItems = (jsonDecode(response!.body) as List)
            .map((i) => WarehouseItem.fromJson(i))
            .toList();
      }
    } catch (e) {
      log("Search Error: $e");
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<bool> deleteEntry(int id) async {
    try {
      final response = await makeRequest(
        '$_baseUrl/outbound?item_id=$id',
        method: 'DELETE',
      );
      if (response?.statusCode == 200) {
        fetchHistory();
        return true;
      }
      return false;
    } catch (e) {
      log("Delete Error: $e");
      return false;
    }
  }

  Future<bool> deleteSelectedItems(List<int> ids) async {
    if (ids.isEmpty) return false;

    _isLoading = true;
    notifyListeners();
    try {
      final response = await makeRequest(
        '$_baseUrl/outbound/batch',
        method: 'DELETE',
        body: ids,
      );
      if (response?.statusCode == 200) {
        fetchHistory();
        return true;
      }
      return false;
    } catch (e) {
      log("Batch Delete Error: $e");
      return false;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<bool> deleteUser(int userId) async {
    try {
      final response = await makeRequest(
        '$_baseUrl/admin/users?user_id=$userId',
        method: 'DELETE',
      );
      if (response?.statusCode == 200) {
        fetchUsers();
        return true;
      }
      return false;
    } catch (e) {
      log("Delete User Error: $e");
      return false;
    }
  }

  Future<bool> clearAllScans() async {
    _isLoading = true;
    notifyListeners();
    try {
      final response = await makeRequest(
        '$_baseUrl/admin/clear/outbound_items',
        method: 'DELETE',
      );
      if (response?.statusCode == 200) {
        fetchHistory();
        return true;
      }
      return false;
    } catch (e) {
      log("Clear Error: $e");
      return false;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<bool> exportScans() async {
    _isLoading = true;
    notifyListeners();
    try {
      final response = await makeRequest('$_baseUrl/admin/export/outbound');
      if (response?.statusCode == 200) {
        final bytes = response!.bodyBytes;
        final fileName =
            "outbound_items_${DateTime.now().millisecondsSinceEpoch}.csv";

        if (kIsWeb) {
          return false;
        } else {
          final directory = await getApplicationDocumentsDirectory();
          final file = File('${directory.path}/$fileName');
          await file.writeAsBytes(bytes);
          await OpenFile.open(file.path);
          return true;
        }
      }
      return false;
    } catch (e) {
      log("Export Error: $e");
      return false;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<bool> closePeriod(List<String> contents) async {
    if (contents.isEmpty) return false;

    _isLoading = true;
    notifyListeners();
    try {
      final response = await makeRequest(
        '$_baseUrl/outbound/close',
        method: 'POST',
        body: contents,
      );
      if (response?.statusCode == 200) {
        final data = jsonDecode(response!.body);
        _lastCloseOutbound = data['outbound'] ?? 0;
        _lastCloseUnknown = data['unknown'] ?? 0;
        _lastCloseOrdersDone = data['orders_done'] ?? 0;
        // WS will trigger list updates, but we need to notify about stats
        notifyListeners();
        return true;
      }
      return false;
    } catch (e) {
      log("Close Period Error: $e");
      return false;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<bool> deleteLabel(String orderSn) async {
    _isLoading = true;
    notifyListeners();
    try {
      final response = await makeRequest(
        '$_baseUrl/labels?order_sn=$orderSn',
        method: 'DELETE',
      );
      if (response?.statusCode == 200) {
        fetchAdminLabels();
        return true;
      }
      return false;
    } catch (e) {
      log("Delete Label Error: $e");
      return false;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> fetchStocks() async {
    _isLoading = true;
    notifyListeners();
    if (_channel == null) await initWebSocket();
    _channel?.sink.add(jsonEncode({'command': 'get_stocks'}));
  }

  Future<bool> exportStocks() async {
    _isLoading = true;
    notifyListeners();
    try {
      final response = await makeRequest('$_baseUrl/admin/export/stocks');
      if (response?.statusCode == 200) {
        final bytes = response!.bodyBytes;
        final fileName =
            "inventory_stocks_${DateTime.now().millisecondsSinceEpoch}.csv";

        if (kIsWeb) {
          return false;
        } else {
          final directory = await getApplicationDocumentsDirectory();
          final file = File('${directory.path}/$fileName');
          await file.writeAsBytes(bytes);
          await OpenFile.open(file.path);
          return true;
        }
      }
      return false;
    } catch (e) {
      log("Export Stocks Error: $e");
      return false;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }
}
