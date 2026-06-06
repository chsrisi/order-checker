import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'app_state.dart';
import 'screens/login_screen.dart';
import 'screens/orders_view.dart';
import 'screens/scanner_view.dart';
import 'screens/item_finder_screen.dart';
import 'screens/stocks_view.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await dotenv.load(fileName: ".env");
  runApp(
    ChangeNotifierProvider(
      create: (context) => AppState()..initialize(),
      child: MyApp(),
    ),
  );
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Item Scanner Client',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.blue),
        useMaterial3: true,
      ),
      home: MyHomePage(title: 'Item Scanner'),
    );
  }
}

class MyHomePage extends StatefulWidget {
  const MyHomePage({super.key, required this.title});

  final String title;

  @override
  State<MyHomePage> createState() => _MyHomePageState();
}

class _MyHomePageState extends State<MyHomePage> {
  // 0: Orders/Inbound, 1: Orders/Outbound, 2: Finder, 3: Stocks, 4: User
  int _navIndex = 0;
  int _subIndex = 0; // 0: Input, 1: History

  void _navigateTo(int index, {VoidCallback? onFetch}) {
    setState(() {
      _navIndex = index;
      _subIndex = 0;
    });
    onFetch?.call();
  }

  @override
  Widget build(BuildContext context) {
    final appState = Provider.of<AppState>(context);

    if (!appState.isLoggedIn) {
      return Scaffold(
        appBar: AppBar(title: Text(widget.title)),
        body: const LoginScreen(),
      );
    }

    Widget body;
    String appBarTitle = widget.title;

    switch (_navIndex) {
      case 0:
        appBarTitle = "Orders · Inbound";
        body = OrdersView(subIndex: _subIndex);
        break;
      case 1:
        appBarTitle = "Orders · Outbound";
        body = ScannerView(subIndex: _subIndex);
        break;
      case 2:
        appBarTitle = "Item Finder";
        body = const ItemFinderScreen();
        break;
      case 3:
        appBarTitle = "Stocks";
        body = StocksView(subIndex: _subIndex);
        break;
      case 4:
        appBarTitle = "Account";
        body = _buildUserView(appState);
        break;
      default:
        body = const Center(child: Text("Page not found"));
    }

    // Sub-tabs apply to Inbound (0), Outbound (1), and Stocks (3)
    final bool hasSubTabs = _navIndex == 0 || _navIndex == 1 || _navIndex == 3;

    return Scaffold(
      appBar: AppBar(
        title: Text(appBarTitle),
        actions: [
          if (appState.isGlobalLoading)
            const Padding(
              padding: EdgeInsets.symmetric(horizontal: 16),
              child: SizedBox(
                width: 20,
                height: 20,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: Colors.blue,
                ),
              ),
            ),
        ],
      ),
      drawer: Drawer(
        child: Column(
          children: [
            DrawerHeader(
              decoration: BoxDecoration(
                color: Theme.of(context).colorScheme.primary,
              ),
              child: const Center(
                child: Text(
                  'Item Scanner',
                  style: TextStyle(color: Colors.white, fontSize: 24),
                ),
              ),
            ),
            // Orders — expandable with Inbound / Outbound
            ExpansionTile(
              leading: const Icon(Icons.shopping_basket),
              title: const Text('Orders'),
              initiallyExpanded: _navIndex == 0 || _navIndex == 1,
              children: [
                ListTile(
                  contentPadding: const EdgeInsets.only(left: 56),
                  leading: const Icon(Icons.inbox, size: 20),
                  title: const Text('Inbound'),
                  selected: _navIndex == 0,
                  onTap: () {
                    _navigateTo(0, onFetch: appState.fetchOrdersData);
                    Navigator.pop(context);
                  },
                ),
                ListTile(
                  contentPadding: const EdgeInsets.only(left: 56),
                  leading: const Icon(Icons.outbox, size: 20),
                  title: const Text('Outbound'),
                  selected: _navIndex == 1,
                  onTap: () {
                    _navigateTo(1, onFetch: appState.fetchHistory);
                    Navigator.pop(context);
                  },
                ),
              ],
            ),
            ListTile(
              leading: const Icon(Icons.search),
              title: const Text('Finder'),
              selected: _navIndex == 2,
              onTap: () {
                _navigateTo(2);
                Navigator.pop(context);
              },
            ),
            ListTile(
              leading: const Icon(Icons.inventory),
              title: const Text('Stocks'),
              selected: _navIndex == 3,
              onTap: () {
                _navigateTo(3, onFetch: appState.fetchStocks);
                Navigator.pop(context);
              },
            ),
            const Spacer(),
            // bottom
            ListTile(
              leading: const Icon(Icons.person),
              title: const Text('Account'),
              selected: _navIndex == 4,
              onTap: () {
                _navigateTo(4);
                Navigator.pop(context);
              },
            ),
          ],
        ),
      ),
      body: Stack(
        children: [
          body,
          if (appState.wsConnectionFailed)
            Positioned(
              top: 0,
              left: 0,
              right: 0,
              child: Container(
                color: Colors.red.withValues(alpha: 0.9),
                padding: const EdgeInsets.all(8),
                child: Row(
                  children: [
                    const Icon(Icons.wifi_off, color: Colors.white),
                    const SizedBox(width: 8),
                    const Expanded(
                      child: Text(
                        "WebSocket Connection Lost",
                        style: TextStyle(color: Colors.white),
                      ),
                    ),
                    TextButton(
                      onPressed: () => appState.retryWebSocket(),
                      child: const Text(
                        "Retry",
                        style: TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
        ],
      ),
      bottomNavigationBar: hasSubTabs
          ? BottomNavigationBar(
              currentIndex: _subIndex,
              onTap: (index) => setState(() => _subIndex = index),
              items: const [
                BottomNavigationBarItem(
                  icon: Icon(Icons.input),
                  label: 'Input',
                ),
                BottomNavigationBarItem(
                  icon: Icon(Icons.history),
                  label: 'History',
                ),
              ],
            )
          : null,
    );
  }

  Widget _buildUserView(AppState appState) {
    final username = appState.username;
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const CircleAvatar(radius: 40, child: Icon(Icons.person, size: 40)),
          const SizedBox(height: 16),
          Text(
            username.isEmpty ? 'User' : username,
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 32),
          FilledButton.icon(
            icon: const Icon(Icons.logout),
            label: const Text('Logout'),
            onPressed: () => appState.handleLogout(),
          ),
        ],
      ),
    );
  }
}
