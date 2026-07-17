import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../app_state.dart';
import '../models.dart';

class BomView extends StatefulWidget {
  const BomView({super.key});

  @override
  State<BomView> createState() => _BomViewState();
}

class _BomViewState extends State<BomView> {
  final _searchController = TextEditingController();
  String _filter = "";
  BOMHeaderEntry? _selectedHeader;

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final appState = Provider.of<AppState>(context);
    var headers = appState.bomHeaders;

    if (_filter.isNotEmpty) {
      final f = _filter.toLowerCase();
      headers = headers.where((h) {
        final matchesSku = h.sku?.toLowerCase().contains(f) ?? false;
        final matchesItemName = h.itemName?.toLowerCase().contains(f) ?? false;
        final matchesModelName =
            h.modelName?.toLowerCase().contains(f) ?? false;
        final matchesId = h.shopeeId?.toString().contains(f) ?? false;
        return matchesSku || matchesItemName || matchesModelName || matchesId;
      }).toList();
    }

    return Padding(
      padding: const EdgeInsets.all(24.0),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Left Side - BOM Header list
          SizedBox(
            width: 380,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  "Bill of Materials",
                  style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                    fontWeight: FontWeight.bold,
                    color: Colors.red.shade900,
                  ),
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: _searchController,
                  decoration: InputDecoration(
                    hintText: "Search BOM by SKU, ID or Name...",
                    prefixIcon: const Icon(Icons.search),
                    isDense: true,
                    filled: true,
                    fillColor: Colors.white,
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                      borderSide: BorderSide(color: Colors.red.shade100),
                    ),
                    enabledBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                      borderSide: BorderSide(color: Colors.red.shade100),
                    ),
                    suffixIcon: _filter.isNotEmpty
                        ? IconButton(
                            icon: const Icon(Icons.clear, size: 18),
                            onPressed: () {
                              setState(() {
                                _searchController.clear();
                                _filter = "";
                              });
                            },
                          )
                        : null,
                  ),
                  onChanged: (val) {
                    setState(() {
                      _filter = val;
                    });
                  },
                ),
                const SizedBox(height: 16),
                Expanded(
                  child: Container(
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(12),
                      boxShadow: [
                        BoxShadow(
                          color: Colors.black.withValues(alpha: 0.05),
                          blurRadius: 10,
                          spreadRadius: 2,
                        ),
                      ],
                    ),
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(12),
                      child: appState.isLoading && appState.bomHeaders.isEmpty
                          ? const Center(child: CircularProgressIndicator())
                          : headers.isEmpty
                          ? const Center(
                              child: Padding(
                                padding: EdgeInsets.all(16.0),
                                child: Text(
                                  "No BOMs match search",
                                  textAlign: TextAlign.center,
                                ),
                              ),
                            )
                          : ListView.separated(
                              itemCount: headers.length,
                              separatorBuilder: (context, index) =>
                                  const Divider(height: 1),
                              itemBuilder: (context, index) {
                                final header = headers[index];
                                final isSelected = _selectedHeader == header;

                                return InkWell(
                                  onTap: () {
                                    setState(() {
                                      _selectedHeader = header;
                                    });
                                    if (header.isMarketplace) {
                                      appState.fetchBOMTree(
                                        shopeeId: header.shopeeId,
                                      );
                                    } else {
                                      appState.fetchBOMTree(sku: header.sku);
                                    }
                                  },
                                  child: Container(
                                    color: isSelected
                                        ? Colors.red.shade50
                                        : Colors.transparent,
                                    padding: const EdgeInsets.symmetric(
                                      horizontal: 16,
                                      vertical: 12,
                                    ),
                                    child: Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        Row(
                                          children: [
                                            Container(
                                              padding:
                                                  const EdgeInsets.symmetric(
                                                    horizontal: 6,
                                                    vertical: 2,
                                                  ),
                                              decoration: BoxDecoration(
                                                color: header.isMarketplace
                                                    ? Colors.purple.shade50
                                                    : Colors.blue.shade50,
                                                borderRadius:
                                                    BorderRadius.circular(4),
                                                border: Border.all(
                                                  color: header.isMarketplace
                                                      ? Colors.purple.shade200
                                                      : Colors.blue.shade200,
                                                ),
                                              ),
                                              child: Text(
                                                header.isMarketplace
                                                    ? "MARKETPLACE"
                                                    : "STANDARD",
                                                style: TextStyle(
                                                  fontSize: 10,
                                                  fontWeight: FontWeight.bold,
                                                  color: header.isMarketplace
                                                      ? Colors.purple.shade800
                                                      : Colors.blue.shade800,
                                                ),
                                              ),
                                            ),
                                            const Spacer(),
                                            if (header.quantityStandard != null)
                                              Text(
                                                "Qty: ${header.quantityStandard}",
                                                style: const TextStyle(
                                                  fontSize: 12,
                                                  color: Colors.grey,
                                                ),
                                              ),
                                          ],
                                        ),
                                        const SizedBox(height: 8),
                                        Text(
                                          header.isMarketplace
                                              ? "${header.itemName ?? ''} ${header.modelName != null && header.modelName!.isNotEmpty ? '(${header.modelName})' : ''}"
                                              : header.itemName ?? 'Unknown',
                                          style: TextStyle(
                                            fontWeight: isSelected
                                                ? FontWeight.bold
                                                : FontWeight.normal,
                                            fontSize: 14,
                                            color: isSelected
                                                ? Colors.red.shade900
                                                : Colors.black87,
                                          ),
                                        ),
                                        const SizedBox(height: 4),
                                        Text(
                                          header.isMarketplace
                                              ? "ID: ${header.shopeeId}"
                                              : "SKU: ${header.sku}",
                                          style: TextStyle(
                                            fontFamily: 'Courier',
                                            fontSize: 12,
                                            color: Colors.grey.shade600,
                                          ),
                                        ),
                                      ],
                                    ),
                                  ),
                                );
                              },
                            ),
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 24),
          // Right Side - Tree Viewer
          Expanded(
            child: Container(
              height: double.infinity,
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(12),
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withValues(alpha: 0.05),
                    blurRadius: 10,
                    spreadRadius: 2,
                  ),
                ],
              ),
              padding: const EdgeInsets.all(24.0),
              child: _buildRightPanel(appState),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildRightPanel(AppState appState) {
    if (_selectedHeader == null) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              Icons.account_tree_outlined,
              size: 80,
              color: Colors.red.shade100,
            ),
            const SizedBox(height: 16),
            Text(
              "Select a BOM from the list",
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.bold,
                color: Colors.red.shade900,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              "Select any standard or marketplace item to resolve and view its recursive bill of materials tree structure.",
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 14, color: Colors.grey.shade600),
            ),
          ],
        ),
      );
    }

    if (appState.isTreeLoading) {
      return const Center(child: CircularProgressIndicator());
    }

    final tree = appState.selectedBomTree;
    if (tree == null) {
      return const Center(child: Text("Could not retrieve BOM tree."));
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Detail Header Card
        Container(
          width: double.infinity,
          decoration: BoxDecoration(
            color: Colors.red.shade50,
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: Colors.red.shade100),
          ),
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                "ROOT ELEMENT RESOLVED",
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.bold,
                  color: Colors.red.shade800,
                  letterSpacing: 1.2,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                tree.name,
                style: const TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: 4),
              if (_selectedHeader!.isMarketplace) ...[
                Text(
                  "Shopee ID: ${_selectedHeader!.shopeeId}   |   Marketplace: ${_selectedHeader!.marketplace ?? 'shopee'}",
                  style: const TextStyle(fontSize: 13, color: Colors.black54),
                ),
              ] else ...[
                Text(
                  "SKU: ${_selectedHeader!.sku}   |   Factor F5: ${_selectedHeader!.factorF5 ?? 'N/A'}",
                  style: const TextStyle(fontSize: 13, color: Colors.black54),
                ),
              ],
            ],
          ),
        ),
        const SizedBox(height: 20),
        Text(
          "Component Tree",
          style: TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.bold,
            color: Colors.grey.shade800,
          ),
        ),
        const SizedBox(height: 12),
        Expanded(
          child: ListView(children: [BOMTreeWidget(node: tree)]),
        ),
      ],
    );
  }
}

class BOMTreeWidget extends StatelessWidget {
  final BOMTreeNode node;
  final int depth;

  const BOMTreeWidget({super.key, required this.node, this.depth = 0});

  @override
  Widget build(BuildContext context) {
    final bool hasChildren = node.children.isNotEmpty;

    final labelColor = node.isNotPrimaryChild
        ? Colors.orange.shade800
        : Colors.blue.shade900;
    final badgeColor = node.isNotPrimaryChild
        ? Colors.orange.shade50
        : Colors.blue.shade50;

    final Widget leadingIcon = node.type == 'marketplace'
        ? const Icon(Icons.storefront, color: Colors.purple)
        : (node.isNotPrimaryChild
              ? const Icon(Icons.subdirectory_arrow_right, color: Colors.orange)
              : const Icon(Icons.inventory, color: Colors.blue));

    final titleWidget = Row(
      children: [
        leadingIcon,
        const SizedBox(width: 8),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                node.name,
                style: const TextStyle(
                  fontWeight: FontWeight.bold,
                  fontSize: 14,
                ),
              ),
              if (node.sku != null && node.sku != node.name)
                Text(
                  "SKU: ${node.sku}",
                  style: TextStyle(
                    color: Colors.grey.shade600,
                    fontSize: 12,
                    fontFamily: 'Courier',
                  ),
                ),
            ],
          ),
        ),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
          decoration: BoxDecoration(
            color: badgeColor,
            borderRadius: BorderRadius.circular(12),
          ),
          child: Text(
            "Qty: ${node.quantity}",
            style: TextStyle(
              color: labelColor,
              fontWeight: FontWeight.bold,
              fontSize: 12,
            ),
          ),
        ),
      ],
    );

    Widget tile;
    if (hasChildren) {
      tile = ExpansionTile(
        title: titleWidget,
        initiallyExpanded: true,
        childrenPadding: const EdgeInsets.only(left: 16.0),
        children: node.children
            .map((child) => BOMTreeWidget(node: child, depth: depth + 1))
            .toList(),
      );
    } else {
      tile = Padding(
        padding: const EdgeInsets.symmetric(vertical: 4.0),
        child: Container(
          decoration: BoxDecoration(
            color: Colors.grey.shade50,
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: Colors.grey.shade200),
          ),
          padding: const EdgeInsets.all(12),
          child: titleWidget,
        ),
      );
    }

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2.0),
      child: tile,
    );
  }
}
