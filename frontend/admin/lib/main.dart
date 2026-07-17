import 'package:admin/models.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'app_state.dart';
import 'views/login_screen.dart';
import 'views/users_view.dart';
import 'views/orders_view.dart';
import 'views/item_finder_view.dart';
import 'views/stocks_view.dart';
import 'views/config_view.dart';
import 'views/account_view.dart';

Future<void> main() async {
  await dotenv.load(fileName: ".env");
  final appState = AppState();
  appState.initialize();

  runApp(
    ChangeNotifierProvider(create: (_) => appState, child: const AdminApp()),
  );
}

class AdminApp extends StatelessWidget {
  const AdminApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Scanner Admin',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.red),
        useMaterial3: true,
      ),
      home: const AdminHomeWrapper(),
    );
  }
}

class AdminHomeWrapper extends StatelessWidget {
  const AdminHomeWrapper({super.key});

  @override
  Widget build(BuildContext context) {
    final isLoggedIn = context.select<AppState, bool>((s) => s.isLoggedIn);

    if (!isLoggedIn) {
      return const LoginScreen();
    }

    return const AdminHomePage();
  }
}

class AdminHomePage extends StatefulWidget {
  const AdminHomePage({super.key});

  @override
  State<AdminHomePage> createState() => _AdminHomePageState();
}

class _AdminHomePageState extends State<AdminHomePage> {
  @override
  Widget build(BuildContext context) {
    final appState = Provider.of<AppState>(context);
    final currentView = appState.currentView;

    Widget body;
    String title;

    switch (currentView) {
      case AdminView.users:
        body = const UsersView();
        title = "Registered Users";
        break;
      case AdminView.orders:
        body = const OrdersView();
        title = "Orders / Labels";
        break;
      case AdminView.finder:
        body = const ItemFinderView();
        title = "Item Finder";
        break;
      case AdminView.stocks:
        body = const StocksView();
        title = "Inventory Stocks";
        break;
      case AdminView.config:
        body = const ConfigView();
        title = "Shopee Configuration";
        break;
      case AdminView.account:
        body = const AccountView();
        title = "Account";
        break;
    }

    // Wrap body with WS error banner when connection has permanently failed
    if (appState.wsConnectionFailed) {
      body = Column(
        children: [
          Material(
            color: Colors.red.shade700,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
              child: Row(
                children: [
                  const Icon(Icons.wifi_off, color: Colors.white, size: 18),
                  const SizedBox(width: 8),
                  const Expanded(
                    child: Text(
                      'Connection lost. Could not reconnect after 5 attempts.',
                      style: TextStyle(color: Colors.white, fontSize: 13),
                    ),
                  ),
                  const SizedBox(width: 8),
                  TextButton(
                    onPressed: appState.retryWebSocket,
                    style: TextButton.styleFrom(
                      backgroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 6,
                      ),
                      minimumSize: Size.zero,
                      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    ),
                    child: Text(
                      'Retry',
                      style: TextStyle(
                        color: Colors.red.shade700,
                        fontWeight: FontWeight.bold,
                        fontSize: 13,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          Expanded(child: body),
        ],
      );
    }

    return Scaffold(
      appBar: AppBar(
        backgroundColor: Colors.red[100],
        title: Text(title),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: appState.loadCurrentViewData,
          ),
        ],
        bottom: appState.isGlobalLoading
            ? const PreferredSize(
                preferredSize: Size.fromHeight(4.0),
                child: LinearProgressIndicator(),
              )
            : null,
      ),
      body: Row(
        children: [
          NavigationRail(
            labelType: NavigationRailLabelType.all,
            trailingAtBottom: true,
            selectedIndex: currentView.isMainView ? currentView.index : null,
            onDestinationSelected: (int index) {
              appState.setView(AdminView.values[index]);
            },
            backgroundColor: Colors.red.shade50,
            selectedIconTheme: const IconThemeData(color: Colors.red),
            selectedLabelTextStyle: const TextStyle(
              color: Colors.red,
              fontWeight: FontWeight.bold,
            ),
            trailing: Column(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                CustomRailItem(
                  labelType: NavigationRailLabelType.all,
                  icon: Icons.person_outline,
                  selectedIcon: Icons.person,
                  label: 'Account',
                  isSelected: currentView == AdminView.account,
                  onTap: () => appState.setView(AdminView.account),
                  isExpanded: false,
                  selectedIconTheme: const IconThemeData(color: Colors.red),
                  selectedLabelTextStyle: const TextStyle(
                    color: Colors.red,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 16),
              ],
            ),

            destinations: const [
              NavigationRailDestination(
                icon: Icon(Icons.people_outline),
                selectedIcon: Icon(Icons.people),
                label: Text('Users'),
              ),
              NavigationRailDestination(
                icon: Icon(Icons.search_outlined),
                selectedIcon: Icon(Icons.search),
                label: Text('Finder'),
              ),
              NavigationRailDestination(
                icon: Icon(Icons.shopping_basket_outlined),
                selectedIcon: Icon(Icons.shopping_basket),
                label: Text('Orders'),
              ),
              NavigationRailDestination(
                icon: Icon(Icons.inventory_2_outlined),
                selectedIcon: Icon(Icons.inventory_2),
                label: Text('Stocks'),
              ),
              NavigationRailDestination(
                icon: Icon(Icons.settings_outlined),
                selectedIcon: Icon(Icons.settings),
                label: Text('Config'),
              ),
            ],
          ),
          const VerticalDivider(thickness: 1, width: 1),
          Expanded(child: body),
        ],
      ),
    );
  }
}
